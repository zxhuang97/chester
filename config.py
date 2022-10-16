import os.path as osp
import os
from chester.autobot_config import *

# TODO change this before make it into a pip package
PROJECT_PATH = osp.abspath(osp.join(osp.dirname(__file__), '..'))

LOG_DIR = os.path.join(PROJECT_PATH, "data")

HOST_ADDRESS = {
    'seuss': 'zixuanhu@seuss.ri.cmu.edu',
    'autobot': 'zixuanhu@autobot.vision.cs.cmu.edu',
    'autobot2': 'zixuanhu@autobot.vision.cs.cmu.edu'
}

# Make sure to use absolute path
REMOTE_DIR = {
    'seuss': '/home/zixuanhu/CDN',
    'autobot': '/home/zixuanhu/CDN',
    'autobot2': '/home/zixuanhu/CDN',
    # 'psc': '/home/xlin3/Projects/softagent',
    # 'nsh': '/home/xingyu/Projects/softagent',
    # 'yertle': '/home/xingyu/Projects/softagent',
    # 'local': '/home/zixuanhu/main_softagent_rpad'
}

REMOTE_MOUNT_OPTION = {
    'seuss': '/usr/share/glvnd',
    'autobot': '/usr/share/glvnd',
    'autobot2': '/usr/share/glvnd',
    # 'psc': '/pylon5/ir5fpfp/xlin3/Projects/baselines_hrl/:/mnt',
}

REMOTE_LOG_DIR = {
    'seuss': os.path.join(REMOTE_DIR['seuss'], "data"),
    # 'seuss': os.path.join('/data/zixuanhu/mpl', "data"),
    'autobot': os.path.join(REMOTE_DIR['autobot'], "data"),
    'autobot2': os.path.join(REMOTE_DIR['autobot2'], "data"),
    # 'psc': os.path.join(REMOTE_DIR['psc'], "data")
    'psc': os.path.join('/mnt', "data")
}

# PSC: https://www.psc.edu/bridges/user-guide/running-jobs
# partition include [RM, RM-shared, LM, GPU]
# TODO change cpu-per-task based on the actual cpus needed (on psc)
# #SBATCH --exclude=compute-0-[7,11]
# Adding this will make the job to grab the whole gpu. #SBATCH --gres=gpu:1
#SBATCH --exclude=compute-0-[5]
#SBATCH --exclude=compute-0-[5,7,9,11,13]
REMOTE_HEADER = dict(seuss="""
#!/usr/bin/env bash
#SBATCH --nodes=1
#SBATCH --partition=GPU
#SBATCH --exclude=compute-0-[5,7,9,11,13]
#SBATCH --cpus-per-task=4
#SBATCH --time=240:00:00
#SBATCH --gres=gpu:1
#SBATCH --mem=40G
""".strip(), psc="""
#!/usr/bin/env bash
#SBATCH --nodes=1
#SBATCH --partition=RM
#SBATCH --ntasks-per-node=18
#SBATCH --time=48:00:00
#SBATCH --mem=64G
""".strip(), psc_gpu="""
#!/usr/bin/env bash
#SBATCH --nodes=1
#SBATCH --partition=GPU-shared
#SBATCH --gres=gpu:p100:1
#SBATCH --ntasks-per-node=4
#SBATCH --time=48:00:00
""".strip(),
autobot="""
#!/usr/bin/env bash
#SBATCH --nodes=1
#SBATCH --partition=long
#SBATCH --exclude=autobot-0-[33]
#SBATCH --cpus-per-task=8
#SBATCH --time=7-00:00:00
#SBATCH --gres=gpu:1
#SBATCH --mem=60G
""".strip(),
autobot2="""
#!/usr/bin/env bash
#SBATCH --nodes=1
#SBATCH --partition=short
#SBATCH --cpus-per-task=5
#SBATCH --time=3-00:00:00
#SBATCH --gres=gpu:1
#SBATCH --mem=45G
""".strip()
)

#!/usr/bin/env bash
#SBATCH --nodes=1
#SBATCH --partition=short
#SBATCH --cpus-per-task=4
#SBATCH --exclude=autobot-0-[9,11],autobot-1-1
#SBATCH --time=3-00:00:00
#SBATCH --gres=gpu:1
#SBATCH --mem=45G

#!/usr/bin/env bash
#SBATCH --nodes=1
#SBATCH --partition=long
#SBATCH --exclude=autobot-0-[17,19,21,23]
#SBATCH --cpus-per-task=12
#SBATCH --time=7-00:00:00
#SBATCH --gres=gpu:1
#SBATCH --mem=60G

#!/usr/bin/env bash
#SBATCH --nodes=1
#SBATCH --partition=short
#SBATCH --cpus-per-task=8
#SBATCH --time=3-00:00:00
#SBATCH --gres=gpu:1
#SBATCH --mem=45G

#!/usr/bin/env bash
#SBATCH --nodes=1
#SBATCH --partition=GPU
#SBATCH --exclude=compute-0-[5,7,9,11,13]
#SBATCH --cpus-per-task=6
#SBATCH --time=240:00:00
#SBATCH --gres=gpu:1
#SBATCH --mem=90G

#!/usr/bin/env bash
#SBATCH --nodes=1
#SBATCH --partition=GPU
#SBATCH --exclude=compute-0-[5,7,9,11,13,17,19,21,25,27,23]
#SBATCH --cpus-per-task=5
#SBATCH --time=240:00:00
#SBATCH --gres=gpu:1
#SBATCH --mem=80G

# location of the singularity file related to the project
SIMG_DIR = {
    'seuss': '/home/zixuanhu/containers/softgymcontainer_v3.simg',
    'autobot': '/home/zixuanhu/softgym_containers/softgymcontainer_v3.simg',
    'autobot2': '/home/zixuanhu/softgym_containers/softgymcontainer_v3.simg',
    # 'psc': '$SCRATCH/containers/ubuntu-16.04-lts-rl.img',
    'psc': '/pylon5/ir5fpfp/xlin3/containers/ubuntu-16.04-lts-rl.img',

}
CUDA_MODULE = {
    'seuss': 'cuda-91',
    # 'autobot': 'cuda-10.2',
    'autobot': 'cuda-11.1.1',
    'autobot2': 'cuda-10.2',
    'psc': 'cuda/9.0',
}
MODULES = {
    'seuss': ['singularity'],
    'autobot': ['singularity'],
    'autobot2': ['singularity'],
    'psc': ['singularity'],
}