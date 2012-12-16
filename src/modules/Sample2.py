from framework.latentmodule import LatentModule
import random
import time

class Main(LatentModule):
    def __init__(self):
        LatentModule.__init__(self)
        
        # set defaults for some configurable parameters:
        self.trials = 5        

    def run(self):
        self.write('We are now testing your reaction times.\nPress the space bar when you are ready.','space')
        self.write('First we will test your keyboard.\nWhen the red rectangle disappears, press the Enter key.',3)
        self.rectangle((-0.5,0.5,-0.2,0.2),duration=3.5,color=(1,0,0,1))
        if self.waitfor('enter',duration=30):
            self.write('Good.',2)
        else:
            self.write('It doesn''t look like you''re pressing the enter key. Ending the experiment.',3)
            return
        
        self.write('Now, whenever the crosshair comes up, press the enter key as fast as possible.\nYou have 3 seconds for each trial. There will be %i trials.\nSpace when ready.' % self.trials,'space')
        
        # countdown
        for k in [3,2,1]:
            self.write(str(k),1,scale=0.2)
        
        all_reaction_times = []
        for k in range(self.trials):
            # wait for a random interval between 2 and 5 seconds
            self.sleep(random.uniform(2,5))
            # show the crosshair and keep it
            self.crosshair(duration=3,block=False)            
            rt = self.watchfor('enter',3)            
            if not rt:
                self.write('Timeout! You didn''t make it.',2,fg=(1,0,0,1))
            elif len(rt) > 1:
                self.write('Oops, you pressed more than one time.',2,fg=(1,0,0,1))
            else:
                self.write('Your reaction time was %g seconds.' % rt[0], duration=2, fg = ((0,1,0,1) if rt[0]<0.5 else (1,1,0,1)))
                all_reaction_times.append(rt[0])

        self.write('Your average reaction time was %g seconds.\nHit the space bar to end the experiment.' % (sum(all_reaction_times)/len(all_reaction_times)),'space')
        
    