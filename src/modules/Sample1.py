from framework.latentmodule import LatentModule
import random

class Main(LatentModule):
    def __init__(self):
        LatentModule.__init__(self)
        
        # set defaults for some configurable parameters:
        self.trials1 = 5            # number of trials in first part
        self.trials2 = 5            # number of trials in second part
        self.a_probability = 0.5    # probability that an "A" appears instead of a "U"

    def run(self):
        self.marker(10)  # emit an event marker to indicate the beginning of the experiment
        self.write('This is a sample experiment.\nYou will be led through a few trials in the following.',2)
        self.write('Press the space bar when you are ready.','space')
        self.write('You will be presented either the letter A or U; \nplease imagine speaking the letter that you see.',2)

        for k in range(self.trials1):
            # show a 3-second crosshair
            self.crosshair(3)
            # display either an A or a U
            if random.random() < self.a_probability:
                self.marker(1)
                self.write('A',scale=0.5)
            else:
                self.marker(2)
                self.write('U',scale=0.5)
                # wait for 2 seconds
            self.sleep(2)

        self.write('You successfully completed the first part of the experiment.')

        self.write('In the second part, you will be presented either a picture of\na monkey eating a banana, or a picture of a tool.',5)
        self.write('The sound of a bell will indicate the end of the experiment.',2)
        for k in range(self.trials2):
            self.crosshair(3)
            if random.random() < 0.5:
                self.marker(3)
                self.picture('monkey.jpg',2,scale=0.3)
            else:
                self.marker(4)
                self.picture('tool.jpg',2,scale=0.3)
            # wait for a an ISI randomly chosen between 1 and 3 seconds
            self.sleep(random.uniform(1,3))

        self.sound('nice_bell.wav',volume=0.5)
        self.write('You have successfully completed the experiment!')
    