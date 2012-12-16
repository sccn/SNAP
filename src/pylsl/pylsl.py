import os,sys,inspect

try:
    binary_path = os.path.realpath(os.path.abspath(os.path.join(os.path.split(inspect.getfile(inspect.currentframe()))[0],"binaries-python" + str(sys.version_info[0]) + "." + str(sys.version_info[1]) + '-' + ('win64' if sys.maxsize>2**32 else 'win32'))))
    if binary_path not in sys.path:
        sys.path.append(binary_path)
except:
    raise Exception("The pylsl module has not been compiled for your Python version.")

from liblsl import *
