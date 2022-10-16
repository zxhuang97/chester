import os
import pdb
import re
import subprocess
import base64
import os.path as osp
import pickle as pickle
import time

import numpy as np
import inspect
import collections
import hashlib
import sys
import datetime
import dateutil.tz
from tempfile import NamedTemporaryFile

from chester import config, config_ec2

from chester.slurm import to_slurm_command
from chester.utils_s3 import launch_ec2, s3_sync_code


def query_yes_no(question, default="yes"):
    """Ask a yes/no question via raw_input() and return their answer.

    "question" is a string that is presented to the user.
    "default" is the presumed answer if the user just hits <Enter>.
        It must be "yes" (the default), "no" or None (meaning
        an answer is required of the user).

    The "answer" return value is True for "yes" or False for "no".
    """
    valid = {"yes": True, "y": True, "ye": True,
             "no": False, "n": False}
    if default is None:
        prompt = " [y/n] "
    elif default == "yes":
        prompt = " [Y/n] "
    elif default == "no":
        prompt = " [y/N] "
    else:
        raise ValueError("invalid default answer: '%s'" % default)

    while True:
        sys.stdout.write(question + prompt)
        choice = input().lower()
        if default is not None and choice == '':
            return valid[default]
        elif choice in valid:
            return valid[choice]
        else:
            sys.stdout.write("Please respond with 'yes' or 'no' "
                             "(or 'y' or 'n').\n")


_find_unsafe = re.compile(r'[a-zA-Z0-9_^@%+=:,./-]').search


def _shellquote(s):
    """Return a shell-escaped version of the string *s*."""
    if not s:
        return "''"

    if _find_unsafe(s) is None:
        return s

    # use single quotes, and put single quotes into double quotes
    # the string $'b is then quoted as '$'"'"'b'

    return "'" + s.replace("'", "'\"'\"'") + "'"


def _to_param_val(v):
    if v is None:
        return ""
    elif isinstance(v, list):
        return " ".join(map(_shellquote, list(map(str, v))))
    else:
        return _shellquote(str(v))


def to_local_command(params, python_command="python", script=osp.join(config.PROJECT_PATH,
                                                                      'scripts/run_experiment.py'),
                     use_gpu=False):
    command = python_command + " " + script

    # for k, v in config.ENV.items():
    #     command = ("%s=%s " % (k, v)) + command
    pre_commands = params.pop("pre_commands", None)
    post_commands = params.pop("post_commands", None)
    if pre_commands is not None or post_commands is not None:
        print("Not executing the pre_commands: ", pre_commands, ", nor post_commands: ", post_commands)

    for k, v in params.items():
        if isinstance(v, dict):
            for nk, nv in v.items():
                if str(nk) == "_name":
                    command += "  --%s %s" % (k, _to_param_val(nv))
                else:
                    command += \
                        "  --%s_%s %s" % (k, nk, _to_param_val(nv))
        else:
            command += "  --%s %s" % (k, _to_param_val(v))
    return command


class AttrDict(dict):
    def __init__(self, *args, **kwargs):
        super(AttrDict, self).__init__(*args, **kwargs)
        self.__dict__ = self


class VariantDict(AttrDict):
    def __init__(self, d, hidden_keys):
        super(VariantDict, self).__init__(d)
        self._hidden_keys = hidden_keys

    def dump(self):
        return {k: v for k, v in self.items() if k not in self._hidden_keys}


class VariantGenerator(dict):
    """
    Usage:

    vg = VariantGenerator()
    vg.add("param1", [1, 2, 3])
    vg.add("param2", ['x', 'y'])
    vg.variants() => # all combinations of [1,2,3] x ['x','y']

    Supports noncyclic dependency among parameters:
    vg = VariantGenerator()
    vg.add("param1", [1, 2, 3])
    vg.add("param2", lambda param1: [param1+1, param1+2])
    vg.variants() => # ..
    """

    def __init__(self):
        self._variants = []
        self._populate_variants()
        self._hidden_keys = []
        for k, vs, cfg in self._variants:
            if cfg.get("hide", False):
                self._hidden_keys.append(k)

    @property
    def size(self):
        return len(self.variants())

    def __getitem__(self, item):
        for param in self.variations():
            if param[0] == item:
                return param[1]

    def add(self, key, vals, **kwargs):
        self._variants.append((key, vals, kwargs))

    def _populate_variants(self):
        methods = inspect.getmembers(
            self.__class__, predicate=lambda x: inspect.isfunction(x) or inspect.ismethod(x))
        methods = [x[1].__get__(self, self.__class__)
                   for x in methods if getattr(x[1], '__is_variant', False)]
        for m in methods:
            self.add(m.__name__, m, **getattr(m, "__variant_config", dict()))

    def variations(self):
        ret = []
        for key, vals, _ in self._variants:
            if not isinstance(vals, list):
                continue
            if len(vals) > 1:
                ret.append(key)
        return ret

    def variants(self, randomized=False):
        ret = list(self.ivariants())
        if randomized:
            np.random.shuffle(ret)
        ret = list(map(self.variant_dict, ret))
        ret[0]['chester_first_variant'] = True
        ret[-1]['chester_last_variant'] = True
        return ret

    def variant_dict(self, variant):
        return VariantDict(variant, self._hidden_keys)

    def to_name_suffix(self, variant):
        suffix = []
        for k, vs, cfg in self._variants:
            if not cfg.get("hide", False):
                suffix.append(k + "_" + str(variant[k]))
        return "_".join(suffix)

    def ivariants(self):
        dependencies = list()
        for key, vals, _ in self._variants:
            if hasattr(vals, "__call__"):
                args = inspect.getfullargspec(vals).args
                if hasattr(vals, 'im_self') or hasattr(vals, "__self__"):
                    # remove the first 'self' parameter
                    args = args[1:]
                dependencies.append((key, set(args)))
            else:
                dependencies.append((key, set()))
        sorted_keys = []
        # topo sort all nodes
        while len(sorted_keys) < len(self._variants):
            # get all nodes with zero in-degree
            free_nodes = [k for k, v in dependencies if len(v) == 0]
            if len(free_nodes) == 0:
                error_msg = "Invalid parameter dependency: \n"
                for k, v in dependencies:
                    if len(v) > 0:
                        error_msg += k + " depends on " + " & ".join(v) + "\n"
                raise ValueError(error_msg)
            dependencies = [(k, v)
                            for k, v in dependencies if k not in free_nodes]
            # remove the free nodes from the remaining dependencies
            for _, v in dependencies:
                v.difference_update(free_nodes)
            sorted_keys += free_nodes
        return self._ivariants_sorted(sorted_keys)

    def _ivariants_sorted(self, sorted_keys):
        if len(sorted_keys) == 0:
            yield dict()
        else:
            first_keys = sorted_keys[:-1]
            first_variants = self._ivariants_sorted(first_keys)
            last_key = sorted_keys[-1]
            last_vals = [v for k, v, _ in self._variants if k == last_key][0]
            if hasattr(last_vals, "__call__"):
                last_val_keys = inspect.getfullargspec(last_vals).args
                if hasattr(last_vals, 'im_self') or hasattr(last_vals, '__self__'):
                    last_val_keys = last_val_keys[1:]
            else:
                last_val_keys = None
            for variant in first_variants:
                if hasattr(last_vals, "__call__"):
                    last_variants = last_vals(
                        **{k: variant[k] for k in last_val_keys})
                    for last_choice in last_variants:
                        yield AttrDict(variant, **{last_key: last_choice})
                else:
                    for last_choice in last_vals:
                        yield AttrDict(variant, **{last_key: last_choice})


def variant(*args, **kwargs):
    def _variant(fn):
        fn.__is_variant = True
        fn.__variant_config = kwargs
        return fn

    if len(args) == 1 and isinstance(args[0], collections.Callable):
        return _variant(args[0])
    return _variant


def rsync_code(remote_host, remote_dir):
    print('Ready to rsync code: remote host: {}, remote_dir: {}'.format(remote_host, remote_dir))
    cmd = 'rsync -avzh --delete --include-from=\'./chester/rsync_include\' --exclude-from=\'./chester/rsync_exclude\' ./ ' + remote_host + ':' + remote_dir
    print(cmd)
    # exit()
    os.system(cmd)


exp_count = -2
now = datetime.datetime.now(dateutil.tz.tzlocal())
timestamp = now.strftime('%m_%d_%H_%M')
remote_confirmed = False


def run_experiment_lite(
        stub_method_call=None,
        batch_tasks=None,
        exp_prefix="experiment",
        exp_name=None,
        log_dir=None,
        script='chester/run_exp_worker.py',  # TODO: change this before making pip package
        python_command="python",
        mode="local",
        use_gpu=False,
        dry=False,
        env=None,
        variant=None,
        variations=[],
        use_cloudpickle=True,
        pre_commands=None,
        print_command=False,
        wait_subprocess=True,
        compile_script=None,
        wait_compile=None,
        use_singularity=True,
        is_vnice=False,
        **kwargs):
    """
    Serialize the stubbed method call and run the experiment using the specified mode.
    :param stub_method_call: A stubbed method call.
    :param script: The name of the entrance point python script
    :param mode: Where & how to run the experiment. Can be ['local', 'singularity', 'seuss', 'psc']
    :param dry: Whether to do a dry-run, which only prints the commands without executing them.
    :param exp_prefix: Name prefix for the experiments
    :param env: extra environment variables
    :param kwargs: All other parameters will be passed directly to the entrance python script.
    :param variant: If provided, should be a dictionary of parameters
    :param
    """
    last_variant = variant.pop('chester_last_variant', False)
    first_variant = variant.pop('chester_first_variant', False)
    local_chester_queue_dir = config.LOG_DIR + '/queues'
    if first_variant:
        os.system(f'mkdir -p {local_chester_queue_dir}')
        # os.system("ssh {host} \'{cmd}\'".format(host=mode, cmd='mkdir -p ' + config.CHESTER_QUEUE_DIR))
    if mode == 'singularity':
        mode = 'local_singularity'
    assert stub_method_call is not None or batch_tasks is not None, "Must provide at least either stub_method_call or batch_tasks"
    if batch_tasks is None:
        batch_tasks = [
            dict(
                kwargs,
                pre_commands=pre_commands,
                stub_method_call=stub_method_call,
                exp_name=exp_name,
                log_dir=log_dir,
                variant=variant,
                use_cloudpickle=use_cloudpickle
            )
        ]

    global exp_count
    global remote_confirmed

    if mode == 'ec2':
        query_yes_no('Confirm: Launching jobs to ec2')
    # pdb.set_trace()
    for task in batch_tasks:
        # time.sleep(3)
        call = task.pop("stub_method_call")
        if use_cloudpickle:
            import cloudpickle
            data = base64.b64encode(cloudpickle.dumps(call)).decode("utf-8")
        else:
            data = base64.b64encode(pickle.dumps(call)).decode("utf-8")
        task["args_data"] = data
        exp_count += 1
        params = dict(kwargs)
        # TODO check params
        if task.get("exp_name", None) is None:
            # task["exp_name"] = "%s_%s_%04d" % (exp_prefix, timestamp, exp_count)
            exp_name = exp_prefix
            for v in variations:
                if isinstance(variant[v], list):
                    continue
                if isinstance(variant[v], str):
                    exp_name += '_{}_{}'.format(v, variant[v])
                elif isinstance(variant[v], bool):
                    if variant[v]:
                        exp_name += '_{}'.format(v)
                else:
                    exp_name += '_{}_{:g}'.format(v, variant[v])
            if mode in ['seuss', 'autobot', 'autobot2']:
                # TODO: change to /data/zixuan
                exp_path = os.path.join(config.REMOTE_LOG_DIR[mode], "train", exp_prefix)
                import glob
                ind = len(glob.glob(exp_path + '*'))
            else:
                ind = 10
            print('exp full name ', exp_name, ind)
            if exp_count == -1:
                exp_count = ind + 1
            task["exp_name"] = "{}_{}".format(exp_name, exp_count)
            print('exp_name : ', task['exp_name'])
        if task.get("log_dir", None) is None:
            # TODO add remote dir here
            print(mode)
            if mode in ['seuss', 'psc', 'autobot', 'autobot2']:
                task["log_dir"] = config.REMOTE_LOG_DIR[mode] + "/train/" + exp_prefix + "/" + task["exp_name"]
                # task['local_dir'] = config.PROJECT_PATH + "/train/" + exp_prefix + "/" + task["exp_name"]
                # task["log_dir"] = config.PROJECT_PATH + "/train/" + exp_prefix + "/" + task["exp_name"]
            else:
                task["log_dir"] = config.LOG_DIR + "/train/" + exp_prefix + "/" + task["exp_name"]
                # task['local_dir'] = config.PROJECT_PATH + "/train/" + exp_prefix + "/" + task["exp_name"]
        remote_batch_dir = config.REMOTE_LOG_DIR[mode] + "/train/"
        local_batch_dir = config.LOG_DIR + "/train/" + exp_prefix
        local_exp_dir = local_batch_dir + "/" + task["exp_name"]
        os.system(f'mkdir -p {local_exp_dir}')

        if task.get("variant", None) is not None:
            variant = task.pop("variant")
            if "exp_name" not in variant:
                variant["exp_name"] = task["exp_name"]
                variant["group_name"] = exp_prefix
            task["variant_data"] = base64.b64encode(pickle.dumps(variant)).decode("utf-8")
        elif "variant" in task:
            del task["variant"]
        task["env"] = task.get("env", dict()) or dict()

    if mode not in ["local", "local2", "local_singularity", "ec2"] and not remote_confirmed and not dry:
        remote_confirmed = query_yes_no(
            "Running in (non-dry) mode %s. Confirm?" % mode)
        if not remote_confirmed:
            sys.exit(1)
    if mode in ["local", "local2"]:
        for task in batch_tasks:
            env = task.pop("env", None)
            command = to_local_command(
                task,
                python_command=python_command,
                script=osp.join(config.PROJECT_PATH, script)
            )
            if print_command:
                print(command)
            if dry:
                return
            try:
                if env is None:
                    env = dict()
                if wait_subprocess:
                    subprocess.call(
                        command, shell=True, env=dict(os.environ, **env))
                    popen_obj = None
                else:
                    popen_obj = subprocess.Popen(
                        command, shell=True, env=dict(os.environ, **env))
            except Exception as e:
                print(e)
                if isinstance(e, KeyboardInterrupt):
                    raise
            return popen_obj
    elif mode == 'local_singularity':
        for task in batch_tasks:
            env = task.pop("env", None)
            command = to_local_command(
                task,
                python_command=python_command,
                script=osp.join(config.PROJECT_PATH, script)
            )
            if print_command:
                print(command)
            if dry:
                return
            try:
                if env is None:
                    env = dict()
                # TODO add argument for specifying container
                singularity_header = 'singularity exec ./chester/containers/ubuntu-16.04-lts-rl.img'
                command = singularity_header + ' ' + command
                subprocess.call(
                    command, shell=True, env=dict(os.environ, **env))
                popen_obj = None
            except Exception as e:
                print(e)
                if isinstance(e, KeyboardInterrupt):
                    raise
            return popen_obj
    elif mode in ['seuss', 'psc', 'satori']:
        for task in batch_tasks:
            # TODO check remote directory
            remote_dir = config.REMOTE_DIR[mode]
            simg_dir = config.SIMG_DIR[mode]
            # query_yes_no('Confirm: Syncing code to {}:{}'.format(mode, remote_dir))
            rsync_code(remote_host=config.HOST_ADDRESS[mode], remote_dir=remote_dir)

            # task["log_dir"] = config.REMOTE_LOG_DIR[mode] + "/local/" + exp_prefix + "/" + task["exp_name"]

            data_dir = task['log_dir']
            if mode == 'psc' and use_gpu:
                header = config.REMOTE_HEADER[mode + '_gpu']
            else:
                header = config.REMOTE_HEADER[mode]
            header = header + "\n#SBATCH -o " + os.path.join(data_dir, 'slurm.out') + " # STDOUT"
            header = header + "\n#SBATCH -e " + os.path.join(data_dir, 'slurm.err') + " # STDERR"
            if simg_dir.find('$') == -1:
                simg_dir = osp.join(remote_dir, simg_dir)
            command_list = to_slurm_command(
                task,
                use_gpu=use_gpu,
                modules=config.MODULES[mode],
                cuda_module=config.CUDA_MODULE[mode],
                header=header,
                python_command=python_command,
                script=osp.join(remote_dir, script),
                use_singularity=use_singularity,
                simg_dir=simg_dir,
                remote_dir=remote_dir,
                mount_options=config.REMOTE_MOUNT_OPTION[mode],
                compile_script=compile_script,
                wait_compile=wait_compile,
                set_egl_gpu=False,
                env=env
            )
            if print_command:
                print("; ".join(command_list))
            command = "\n".join(command_list)
            script_name = './' + task['exp_name']
            remote_script_name = os.path.join(remote_dir, data_dir, task['exp_name'])
            print(data_dir)
            with open(script_name, 'w') as f:
                f.write(command)
            print('Executing create folder', data_dir)
            # os.system("ssh {host} \'{cmd}\'".format(host=config.HOST_ADDRESS[mode], cmd='mkdir -p ' + os.path.join(remote_dir, data_dir)))
            os.system("ssh {host} \'{cmd}\'".format(host=config.HOST_ADDRESS[mode], cmd='mkdir -p ' + data_dir))
            cmd = 'scp -o ProxyJump=zixuanhu@ss {f1} {host}:{f2}'.format(f1=script_name, f2=remote_script_name,
                                                                         host=config.HOST_ADDRESS[mode])
            print('Executing cp script: ', cmd)
            os.system(cmd)  # Copy script
            if not dry:
                cmd = "ssh -J zixuanhu@ss " + config.HOST_ADDRESS[mode] + " \'sbatch " + remote_script_name + "\'"
                print('Submit to slurm ', cmd)
                os.system(cmd)  # Launch
            # Cleanup
            os.remove(script_name)
    elif mode in ['autobot']:
        for task in batch_tasks:
            # TODO check remote directory
            remote_dir = config.REMOTE_DIR[mode]
            simg_dir = config.SIMG_DIR[mode]
            # query_yes_no('Confirm: Syncing code to {}:{}'.format(mode, remote_dir))
            if first_variant:
                rsync_code(remote_host=mode, remote_dir=remote_dir)
            data_dir = task['log_dir']
            # data_dir = os.path.join('data', 'local', exp_prefix, task['exp_name'])
            remote_script_name = os.path.join(data_dir, task['exp_name'])
            local_script_name = os.path.join(local_exp_dir, task['exp_name'])
            header = '#CHESTERNODE ' + ','.join(config.AUTOBOT_NODELIST)
            header = header + "\n#CHESTEROUT " + os.path.join(data_dir, 'slurm.out')
            header = header + "\n#CHESTERERR " + os.path.join(data_dir, 'slurm.err')
            header = header + "\n#CHESTERSCRIPT " + remote_script_name
            if simg_dir.find('$') == -1:
                simg_dir = osp.join(remote_dir, simg_dir)
            command_list = to_slurm_command(
                task,
                use_gpu=use_gpu,
                modules=config.MODULES[mode],
                cuda_module=config.CUDA_MODULE[mode],
                header=header,
                python_command=python_command,
                use_singularity=use_singularity,
                script=osp.join(remote_dir, script),
                simg_dir=simg_dir,
                remote_dir=remote_dir,
                mount_options=config.REMOTE_MOUNT_OPTION[mode],
                compile_script=compile_script,
                wait_compile=wait_compile,
                set_egl_gpu=True,
                is_vnice=is_vnice,
            )
            if print_command:
                print("; ".join(command_list))
            command = "\n".join(command_list)
            script_name = './data/tmp/' + task['exp_name']
            scheduler_script_name = os.path.join(local_chester_queue_dir, task['exp_name'])
            with open(script_name, 'w') as f:
                f.write(command)
            # pdb.set_trace()
            # os.system("ssh {host} \'{cmd}\'".format(host=mode, cmd='mkdir -p ' + os.path.join(data_dir)))
            # os.system('scp {f1} {host}:{f2}'.format(f1=script_name, f2=remote_script_name, host=mode))  # Copy script
            # os.system('scp {f1} {host}:{f2}'.format(f1=script_name, f2=scheduler_script_name, host=mode))
            os.system(f'cp {script_name} {local_script_name}')
            os.system(f'cp {script_name} {scheduler_script_name}')
            # Cleanup
            os.remove(script_name)
            # Open scheduler if all jobs have been submitted
            # Remote end will only open another scheduler when there is not one running already
            # Redirect the output of the remote scheduler to the log file
            if last_variant:
                os.system('scp -r {f1} {host}:{f2}'.format(f1=local_batch_dir, f2=remote_batch_dir, host=mode))
                os.system('scp -r {f1} {host}:{f2}'.format(f1=local_chester_queue_dir, f2=config.CHESTER_QUEUE_DIR,
                                                           host=mode))
                os.system(f'rm -rf {local_batch_dir}')
                os.system(f'rm -rf {local_chester_queue_dir}')
                # os.system("ssh {host} \'{cmd}\'".format(host=mode, cmd='mkdir -p ' + config.CHESTER_CHEDULER_LOG_DIR))
                t = datetime.datetime.now(dateutil.tz.tzlocal()).strftime('%m_%d_%H_%M')
                # log_file = os.path.join(config.CHESTER_CHEDULER_LOG_DIR, f'{t}.txt')
                log_file = os.path.join(config.CHESTER_CHEDULER_LOG_DIR, f'log_{t}.txt')
                print('Ready to execute the scheduler')
                cmd = "ssh  {host} \'{cmd} > {output}&\'".format(host=mode,
                                                                 cmd=f'cd {remote_dir} && . ./prepare.sh && nohup python chester/scheduler/remote_scheduler.py',
                                                                 output=log_file)
                if dry:
                    print(remote_script_name)
                    print(cmd)
                else:
                    os.system(cmd)

    elif mode == 'csail':
        # Launcher is running on the compute node, so no needed to sync codes
        available_nodes = []
        for task in batch_tasks:
            command = to_local_command(
                task,
                python_command=python_command,
                script=osp.join(config.PROJECT_PATH, script)
            )
            if print_command:
                print(command)
            remote_dir = config.REMOTE_DIR[mode]
            print

    elif mode == 'ec2':
        # if docker_image is None:
        #     docker_image = config.DOCKER_IMAGE
        s3_code_path = s3_sync_code(config_ec2, dry=dry)
        for task in batch_tasks:
            task["remote_log_dir"] = osp.join(config_ec2.AWS_S3_PATH, exp_prefix.replace("_", "-"), task["exp_name"])
            if compile_script is None:
                task["pre_commands"] = [". ./prepare_ec2.sh", 'time ./compile.sh']
            else:
                task["pre_commands"] = [". ./prepare_ec2.sh", 'time ./' + compile_script]
        launch_ec2(batch_tasks,
                   exp_prefix=exp_prefix,
                   docker_image=None,  # Currently not using docker
                   python_command=python_command,
                   script=script,
                   aws_config=None,
                   dry=dry,
                   terminate_machine=True,
                   use_gpu=use_gpu,
                   code_full_path=s3_code_path,
                   sync_s3_pkl=True,
                   sync_s3_html=True,
                   sync_s3_png=True,
                   sync_s3_log=True,
                   sync_s3_gif=True,
                   sync_s3_mp4=True,
                   sync_s3_pth=True,
                   sync_s3_txt=True,
                   sync_log_on_termination=True,
                   periodic_sync=True,
                   periodic_sync_interval=15)
