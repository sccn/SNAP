from framework.latentmodule import LatentModule
import random
import time

class Main(LatentModule):
    def __init__(self):
        LatentModule.__init__(self)
        self.conditions = ['congruent', 'incongruent']  # Congruent/incongruent right/left
        self.n_blocks = 3  # Number of blocks of 14 unique trials
        self.n_runs = 10  # Number of runs (i.e. the number of random blocks)
        self.stim_duration = 0.15
        self.pre_duration = [0, 0.033, 0.066, 0.1, 0.133, 0.166, 0.2]
        self.trial_duration = 1.65
        self.thresholds = [0.9, 0.6]  # Thresholds of accuracy for congruent and incongruent
        self.stimulus_images = ['target_R_C.bmp', 'target_L_C.bmp', 'target_R_I.bmp', 'target_L_I.bmp']
        self.pre_images = ['flankers_R.bmp', 'flankers_L.bmp']
        
    def run(self):
        self.implicit_markers = False
        base.win.setClearColor((1, 1, 1, 1))  # White background
        
        self.marker(0)  # Send one event to trigger the whole event sending process
        
        # Precache images
        for f in self.stimulus_images:
            self.precache_picture(f)
        for f in self.pre_images:
            self.precache_picture(f)
        
        # Create log file
        t = time.localtime()
        t_str = '-'.join([str(k) for k in [t.tm_year, t.tm_mon, t.tm_mday, t.tm_hour, t.tm_min, t.tm_sec]])

        f = open('studies/flanker_arrows/log/' + t_str + '.txt', 'w')
        f.write('Trial\tCondition\tDelay\tResponse\tReaction time\n')
        
        # Show instructions
        if self.training:
            self.write('We\'re now going to show you three arrows\nwhich will quickly appear\non top of each other on the screen.\nIMPORTANT!\nOnly look at the arrow in the middle.',
                       duration='mouse1', align='center', pos=(0, 0), scale=0.1, fg=(0, 0, 0, 1))
            self.picture(self.pre_images[0],
                       duration='mouse1', block=True, scale=(0.1, 0.2), pos=(0, 0))
            self.picture(self.pre_images[1],
                       duration='mouse1', block=True, scale=(0.1, 0.2), pos=(0, 0))
            self.write('Only click in the direction the arrow is pointing to.\nClick as quickly as you can.',
                       duration='mouse1', align='center', pos=(0, 0), scale=0.1, fg=(0, 0, 0, 1))
            self.write('Click as quickly as you can\nand try not to make too many mistakes.\nIn the breaks, the computer\nwill tell you if you should click more quickly\nor more accurately.', 
                       duration='mouse1', align='center', pos=(0, 0), scale=0.1, fg=(0, 0, 0, 1))
            self.write('It\'s very important that you observe the feedback!\nIf you are requested to go faster, please do so.\nIf you are requested to be more accurate,\nplease be more careful in your responses.', 
                       duration='mouse1', align='center', pos=(0, 0), scale=0.1, fg=(0, 0, 0, 1))
        self.write('We\'re going to start in a minute.\nPlease sit as still as you can during the test.',
                   duration='mouse1', align='center', pos=(0, 0), scale=0.1, fg=(0, 0, 0, 1))
        self.sleep(2)
        
        for run in range(self.n_runs):  # Feedback is shown after each run
            # Generate randomized stimuli
            stimuli = []
            for condition in range(len(self.conditions)):
                for delay in range(len(self.pre_duration)):
                    stimuli.append([condition, delay])
            stimuli *= self.n_blocks
            random.shuffle(stimuli)
            
            correct_congruent, correct_incongruent = 0.0, 0.0  # Number of correct responses
            number_congruent, number_incongruent = 0, 0
            
            for trial_number, trial in enumerate(stimuli):
                
                f.write(str(trial[0]) + '\t' + str(trial[1]) + '\t')
                
                watcher = self.watchfor_multiple_begin(['mouse1', 'mouse3'])
                
                left_right = random.randint(0, 1)  # Randomly choose left or right arrow (target)
                print "Trial {0}, {1}, delay {2}, left/right {3}".format(trial_number + 1, trial[0], trial[1], left_right)
                # Show pre-stimulus picture
                if trial[1] > 0:  # If the delay is 0, don't show the flanker image
                    if (left_right == 0 and trial[0] == 0) or (left_right == 1 and trial[0] == 1):  # Right
                        self.picture(self.pre_images[0], duration=self.pre_duration[trial[1]], block=True, scale=(0.1, 0.2), pos=(0, 0))
                    else:  # Left
                        self.picture(self.pre_images[1], duration=self.pre_duration[trial[1]], block=True, scale=(0.1, 0.2), pos=(0, 0))
                
                # Show stimulus
                if trial[0] == 0:  # congruent
                    self.picture(self.stimulus_images[left_right], duration=self.stim_duration, block=True, scale=(0.1, 0.2), pos=(0, 0))
                    number_congruent += 1
                    self.marker(trial[1] + 10000)
                else:  # incongruent
                    self.picture(self.stimulus_images[left_right + 2], duration=self.stim_duration, block=True, scale=(0.1, 0.2), pos=(0, 0))
                    number_incongruent += 1
                    self.marker(trial[1] + 11000)
                
                # Event markers: 1000x ... congruent, 1100x ... incongruent (x = 0...6 is the delay)
                self.crosshair(self.trial_duration - self.pre_duration[trial[1]] - self.stim_duration, block=True, pos=(0, 0), size=0.025, width=0.005)
                
                responses = self.watchfor_multiple_end(watcher)
                
                first_event_1 = responses['mouse1'][0] if responses['mouse1'] else None
                first_event_3 = responses['mouse3'][0] if responses['mouse3'] else None
                
                if first_event_1 == None and first_event_3 == None:  # No response
                    reaction_time = None
                    mouse_button = None
                elif first_event_1 == None:
                    reaction_time = first_event_3
                    mouse_button = 3
                elif first_event_3 == None:
                    reaction_time = first_event_1
                    mouse_button = 1
                else:
                    reaction_time = first_event_1 if first_event_1 < first_event_3 else first_event_3
                    mouse_button = 1 if first_event_1 < first_event_3 else 3    
                
                    
                if mouse_button is None:  # No response
                    f.write('Incorrect\t-\n')
                    print "Incorrect"
                elif (mouse_button == 1 and left_right == 1) or (mouse_button == 3 and left_right == 0):  # Correct response
                    f.write('Correct\t' + str(reaction_time) + '\n')
                    print "Correct, {0}".format(reaction_time)
                    if trial[0] == 0:
                        correct_congruent += 1
                    else:
                        correct_incongruent += 1
                else:  # Incorrect response
                    f.write('Incorrect\t' + str(reaction_time) + '\n')
                    print "Incorrect, {0}".format(reaction_time)
                
                try:
                    congruent_accuracy =  correct_congruent/number_congruent
                except ZeroDivisionError:
                    congruent_accuracy = None
                    
                try:
                    incongruent_accuracy =  correct_incongruent/number_incongruent
                except ZeroDivisionError:
                    incongruent_accuracy = None
                      
                print '******', congruent_accuracy, incongruent_accuracy, '******'
    
            if run < self.n_runs - 1:  # Show feedback after every run (but not after the last run)
                if congruent_accuracy is None:
                    congruent_accuracy = 0
                if incongruent_accuracy is None:
                    incongruent_accuracy = 0
                
                if ((congruent_accuracy > self.thresholds[0]) and 
                    (self.thresholds[1] < incongruent_accuracy < self.thresholds[0]) and 
                    (congruent_accuracy > incongruent_accuracy + 0.1)):
                    self.write('Great! Continue exactly\nas you''re doing!', duration=5, align='center', pos=(0, 0), scale=0.1, fg=(0, 0, 0, 1))
                elif (congruent_accuracy < self.thresholds[0]) or (incongruent_accuracy < self.thresholds[1]):
                    self.write('Good, but can you be\na bit more accurate, please!', duration=5, align='center', pos=(0, 0), scale=0.1, fg=(0, 0, 0, 1))
                elif (congruent_accuracy > self.thresholds[0]) and (incongruent_accuracy > self.thresholds[1]):
                    self.write('Good, but can you go\na bit more quickly, please!', duration=5, align='center', pos=(0, 0), scale=0.1, fg=(0, 0, 0, 1))
                else:
                    self.write('Good!', duration=5, align='center', pos=(0, 0), scale=0.1, fg=(0, 0, 0, 1))
            
        f.close()
