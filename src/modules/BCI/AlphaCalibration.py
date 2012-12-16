from framework.latentmodule import LatentModule

class Main(LatentModule):
    def __init__(self):
        LatentModule.__init__(self)
        
        # set defaults for some configurable parameters:
        self.awake_duration = 10                 # duration of the awake condition
        self.snooze_duration = 10                # duration of the zone-out condition
        self.wakeup_sound = 'nice_bell.wav'      # sound to indicate the end of the zone-out condition
        self.transition_duration = 1.5           # time that the subject has to come back

        self.moviefile = 'big\\alpha_movie2.avi'
        self.begintime = 0.0                    # time into the movie where we begin playing
        self.endtime = 3.5*60                   # time into the movie where we end
        
    def run(self):
        self.marker(10)  # emit an event marker to indicate the beginning of the experiment
        self.write('This experiment is about high or low-intensity visual perception. You will be presented a sequence of trials, during half of which you will see a movie (with a fixation cross in the middle), and during the other half of which you will see just the fixation cross. When you see the movie, keep fixating, but focus on the content. When you see only the cross, try to defocus your vision, think nothing, and just wait for the bell that indicates the beginning of the next trial. Please press the space bar when you are ready.','space',wordwrap=30,pos=[0,0.3])

        for k in [3,2,1]:
            self.write('Experiment begins in '+str(k))

        self.trials = int((self.endtime-self.begintime)/self.awake_duration)
        for t in range(self.trials):

            # show a piece of the movie, superimposed with a fixation cross
            self.marker(1)
            m = self.movie(self.moviefile, block=False, scale=[0.7,0.4],aspect=1.125,contentoffset=[0,0],volume=0.3,timeoffset=self.begintime+t*self.awake_duration,looping=True)
            self.crosshair(self.awake_duration,size=0.2,width=0.005)
            m[0].stop()
            m[2].removeNode()
            self.marker(2)
            self.sleep(self.transition_duration)

            # show just the cross-hair
            self.marker(3)
            self.crosshair(self.snooze_duration,size=0.2,width=0.005)

            # play the "wakeup" sound
            self.sound(self.wakeup_sound)
            self.marker(4)
            self.sleep(self.transition_duration)
                        
        self.write('You successfully completed the experiment!')
