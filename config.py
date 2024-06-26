import os.path as osp
import os
from chester.autobot_config import *

PROJECT_PATH = osp.abspath(osp.join(osp.dirname(__file__), '..'))

LOG_DIR = os.path.join(PROJECT_PATH, "data")

HOST_ADDRESS = {
    'seuss': 'zixuanhu@seuss.ri.cmu.edu',
    'autobot': 'zixuanhu@autobot.vision.cs.cmu.edu',
    'autobot2': 'zixuanhu@autobot.vision.cs.cmu.edu',
    'gl': "zixuanh@gl",
    "armdual": "armdual.local",
    'local': "",
}

# Make sure to use absolute path
REMOTE_DIR = {
    'seuss': '/home/zixuanhu/UMD',
    'autobot': '/home/zixuanhu/UMD',
    'gl': "/home/zixuanh/UMD",
    "armdual": "/home/zixuanh/UMD",
    'local': "/home/zixuanh/UMD"
}

REMOTE_MOUNT_OPTION = {
    'seuss': '/usr/share/glvnd',
    'gl': '/usr/share/glvnd',
    'autobot': '/usr/share/glvnd',
}

REMOTE_LOG_DIR = {
    'seuss': os.path.join(REMOTE_DIR['seuss'], "data"),
    'autobot': os.path.join(REMOTE_DIR['autobot'], "data"),
    "gl": os.path.join(REMOTE_DIR["gl"], "data"),
    'psc': os.path.join('/mnt', "data"),
    'local':  os.path.join(REMOTE_DIR['local'], "data"),
    'armdual':  os.path.join(REMOTE_DIR['armdual'], "data"),
}

REMOTE_HEADER = dict(gl="""
#!/usr/bin/env bash
#SBATCH --nodes=1
#SBATCH --partition=spgpu
#SBATCH --cpus-per-gpu=4
#SBATCH --time=72:00:00
#SBATCH --gpus=$gpus
#SBATCH --ntasks-per-node=$gpus
#SBATCH --mem-per-gpu=48G
#SBATCH --gpu_cmode=shared
""".strip(),
gl2="""
#!/usr/bin/env bash
#SBATCH --nodes=1
#SBATCH --partition=spgpu,gpu_mig40
#SBATCH --cpus-per-task=4
#SBATCH --time=72:00:00
#SBATCH --gres=gpu:1
#SBATCH --mem=48G
""".strip(),
autobot="""
#!/usr/bin/env bash
#SBATCH --nodes=1
#SBATCH --partition=short
#SBATCH --cpus-per-task=8
#SBATCH --exclude=autobot-0-[9,11,17]
#SBATCH --time=3-00:00:00
#SBATCH --gres=gpu:1
#SBATCH --mem=45G
""".strip(),
)


# location of the singularity file related to the project
SIMG_PATH = {
    'gl': None,
    'seuss': '/home/zixuanhu/containers/softgymcontainer_v3.simg',
    'autobot': '/home/zixuanhu/softgym_containers/ubuntu20.sif',
}
CUDA_MODULE = {
    'seuss': 'cuda-91',
    "gl": 'cuda/12.1.1',
    'autobot': 'cuda-11.1.1',
    'autobot2': 'cuda-10.2',
    'psc': 'cuda/9.0',
}
MODULES = {
    'seuss': ['singularity'],
    'gl': ['singularity'],
    'autobot': ['singularity'],
    'autobot2': ['singularity'],
    'psc': ['singularity'],
}