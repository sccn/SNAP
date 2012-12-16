from framework.latentmodule import LatentModule
from panda3d.core import TextProperties, TextPropertiesManager

class Main(LatentModule):
    def __init__(self):
        LatentModule.__init__(self)
         
    def run(self):
        self.implicit_markers = False
        base.win.setClearColor((0, 0, 0, 1))
        
        self.marker(0)  # Send one event to trigger the whole event sending process
      
        # Define text properties
        tp_gray = TextProperties()
        tp_gray.setTextColor(0.5, 0.5, 0.5, 1)
        tpMgr = TextPropertiesManager.getGlobalPtr()
        tpMgr.setProperties("gray", tp_gray)
        
        self.write('When you are ready,\npress the space bar to begin.' + 
                   '\n\n\1gray\1[Press Space to continue]\2', duration='space', align='left', pos=(-0.5, 0), scale=0.05, fg=(1, 1, 1, 1))    
        
        self.sleep(4)
        self.watchfor('space')
