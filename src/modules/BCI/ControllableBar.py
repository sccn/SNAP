from framework.latentmodule import LatentModule

class Main(LatentModule):
    def __init__(self):
        LatentModule.__init__(self)

        # set defaults for some configurable parameters:
        self.bci = 1.5     # this variable shall be controlled by a BCI (between 1 and 2)
        
    def run(self):
        import socket
        self.write('Your hostname is "' + socket.getfqdn() + '".\nPlease press the space bar when you are ready.','space',wordwrap=30)
        
        for k in [3,2,1]:
            self.write('Experiment begins in '+str(k))

        # show a cross-hair indefinitely
        self.crosshair(100000,size=0.2,width=0.005,block=False)
        while True:
            # show a vertical bar, extent defined by the BCI channel
            self.rectangle([max(0,self.bci-1.5),min(0,self.bci-1.5),-0.05,0.05], 0.05,color=[0,0,0,1])

