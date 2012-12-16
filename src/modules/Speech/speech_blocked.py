from framework.latentmodule import LatentModule
from panda3d.core import TextProperties, TextPropertiesManager
import random
import time

class Main(LatentModule):
    def __init__(self):
        LatentModule.__init__(self)
        
        self.tasks = ['overt', 'covert', 'none']
        with open('studies/speech/stimuli.txt', 'r') as f:
            self.stimuli = f.readlines()
        self.conditions = ['visual', 'auditory']

        self.n_blocks = len(self.tasks) * len(self.conditions)
        self.n_runs = 4
        self.pause = 0.75
        
    def run(self):
        self.implicit_markers = False
        base.win.setClearColor((0, 0, 0, 1))
        
        # Precache sounds
        self.file_list_f = ['studies/speech/stimuli/' + k.strip() + '_f.wav' for k in self.stimuli]
        for f in self.file_list_f:
            self.precache_sound(f)
        self.file_list_m = ['studies/speech/stimuli/' + k.strip() + '_m.wav' for k in self.stimuli]
        for f in self.file_list_m:
            self.precache_sound(f)
        
        # Define text properties
        tp_gray = TextProperties()
        tp_gray.setTextColor(0.5, 0.5, 0.5, 1)
        tpMgr = TextPropertiesManager.getGlobalPtr()
        tpMgr.setProperties("gray", tp_gray)
        
        # Show instructions
        if self.training:
            self.n_runs = 1
            self.write('This is a speech perception/production\n' +           'experiment. You will complete several trials\n' +
                       'in each block.\n\n' + 
                       '\1gray\1[Press Space to continue]\2', duration='space', align='left', pos=(-0.5, 0), scale=0.05, fg=(1, 1, 1, 1))
            self.write('The experiment consists of three conditions.\n' + 
                       'You will perform one of these tasks:\n\n' +
                       '(1) Speak a word\n' + 
                       '(2) Imagine speaking a word\n' + 
                       '(3) Press the Space bar' +
                       '\n\n\1gray\1[Press Space to continue]\2', duration='space', align='left', pos=(-0.5, 0), scale=0.05, fg=(1, 1, 1, 1))
            self.write('You will be instructed which task to perform\n' + 
                       'at the beginning of each block.\n\n' + 
                       'Specifically, the tasks are as follows:\n\n' +
                       '\1gray\1[Press Space to continue]\2', duration='space', align='left', pos=(-0.5, 0), scale=0.05, fg=(1, 1, 1, 1))
            txt = self.write('(1) Speak the word aloud.\n\n' +
                             'You will either see or hear the word.\n\n' +
                             '\1gray\1[Press Space to continue]\2', duration=10000, block=False, align='left', pos=(-0.5, 0), scale=0.05, fg=(1, 1, 1, 1))
            pic = self.picture('studies/speech/overt.png', duration=10000, block=False, scale=0.25, pos=(0, 0.5))
            self.waitfor('space')
            txt.destroy()
            pic.destroy()
            txt = self.write('(2) Imagine speaking the word.\n\n' +
                             'You will either see or hear the word.\n\n' +
                             '\1gray\1[Press Space to continue]\2', duration=10000, block=False, align='left', pos=(-0.5, 0), scale=0.05, fg=(1, 1, 1, 1))
            pic = self.picture('studies/speech/covert.png', duration=10000, block=False, scale=0.25, pos=(0, 0.5))
            self.waitfor('space')
            txt.destroy()
            pic.destroy()
            txt = self.write('(3) Press the Space bar when the word\n' +
                             'was green or when the word was spoken\n' +
                             'by a female voice.\n\n' +
                             '\1gray\1[Press Space to continue]\2', duration=10000, block=False, align='left', pos=(-0.5, 0), scale=0.05, fg=(1, 1, 1, 1))
            pic = self.picture('studies/speech/control.png', duration=10000, block=False, scale=0.25, pos=(0, 0.5))
            self.waitfor('space')
            txt.destroy()
            pic.destroy()
            
        self.write('When you are ready,\npress the Space bar to begin.' + 
                   '\n\n\1gray\1[Press Space to continue]\2', duration='space', align='left', pos=(-0.5, 0), scale=0.05, fg=(1, 1, 1, 1))    
        
        # Create log file
        t = time.localtime()
        t_str = '-'.join([str(k) for k in [t.tm_year, t.tm_mon, t.tm_mday, t.tm_hour, t.tm_min, t.tm_sec]])
        f = open('studies/speech/log/' + t_str + '.txt', 'w')

        for run in range(self.n_runs):
            # Create randomized block sequence
            blocks = []
            for i1 in range(len(self.tasks)):   # Task (overt, covert, none)
                for i2 in range(len(self.conditions)):   # Condition (visual, auditory)
                    blocks.append([i1, i2])
            random.shuffle(blocks)

            for block in blocks:
                # Create randomized stimulus presentation sequence
                trials = range(len(self.stimuli))
                random.shuffle(trials)
                
                # Show instructions
                if block[0] == 0:  # Overt
                    if block[1] == 0:  # Visual
                        txt = self.write('You will see words on the screen.\n\n' +
                                         'Speak the word aloud.\n\n' +
                                         '\1gray\1[Press Space to continue]\2', duration=10000, block=False, align='left', pos=(-0.5, 0), scale=0.05, fg=(1, 1, 1, 1))
                    elif block[1] == 1:  # Auditory
                        txt = self.write('You will hear words.\n\n' +
                                         'Speak the word aloud.\n\n' +
                                         '\1gray\1[Press Space to continue]\2', duration=10000, block=False, align='left', pos=(-0.5, 0), scale=0.05, fg=(1, 1, 1, 1))
                    pic = self.picture('studies/speech/overt.png', duration=10000, block=False, scale=0.25, pos=(0, 0.5))
                elif block[0] == 1:  # Covert
                    if block[1] == 0:  # Visual
                        txt = self.write('You will see words on the screen.\n\n' +
                                         'Imagine speaking the word.\n\n' +
                                         '\1gray\1[Press Space to continue]\2', duration=10000, block=False, align='left', pos=(-0.5, 0), scale=0.05, fg=(1, 1, 1, 1))
                    elif block[1] == 1:  # Auditory
                        txt = self.write('You will hear words.\n\n' +
                                         'Imagine speaking the word.\n\n' +
                                         '\1gray\1[Press Space to continue]\2', duration=10000, block=False, align='left', pos=(-0.5, 0), scale=0.05, fg=(1, 1, 1, 1))
                    pic = self.picture('studies/speech/covert.png', duration=10000, block=False, scale=0.25, pos=(0, 0.5))
                elif block[0] == 2:  # Control
                    if block[1] == 0:  # Visual
                        txt = self.write('You will see words on the screen.\n\n' +
                                         'Press the Space bar if the words was green.\n\n' +
                                         '\1gray\1[Press Space to continue]\2', duration=10000, block=False, align='left', pos=(-0.5, 0), scale=0.05, fg=(1, 1, 1, 1))
                    elif block[1] == 1:  # Auditory
                        txt = self.write('You will hear words.\n\n' +
                                         'Press the Space bar if the voice was female.\n\n' +
                                         '\1gray\1[Press Space to continue]\2', duration=10000, block=False, align='left', pos=(-0.5, 0), scale=0.05, fg=(1, 1, 1, 1))
                    pic = self.picture('studies/speech/control.png', duration=10000, block=False, scale=0.25, pos=(0, 0.5))
                    
                self.waitfor('space')
                txt.destroy()
                pic.destroy()
                self.sleep(4)
                
                if self.training:
                    trials = trials[:8]  # Use only the first 16 items for the training block
                            
                for trial in trials:
                    rand_color_voice = random.randint(0, 1)  # 0 ... blue word, female voice; 1 ... green word, male voice
                    f.write(self.stimuli[trial].strip() + '\t' + self.tasks[block[0]] + '\t' + self.conditions[block[1]] + '\t' + str(rand_color_voice) + '\t')
                    self.marker(k)
    
                    if rand_color_voice == 0:  # Blue text, female voice
                        if self.conditions[block[1]] == 'visual':
                            self.write(self.stimuli[trial], duration=self.isi-self.pause, block=False, scale=0.15, fg=(0, 0.666667, 1, 1))
                        else:
                            self.sound(self.file_list_f[trial], volume=0.5) 
                            self.write('+', duration=self.isi-self.pause, block=False, scale=0.15, fg=(1, 1, 1, 1))
                    else:  # Green text, male voice
                        if self.conditions[block[1]] == 'visual':
                            self.write(self.stimuli[trial], duration=self.isi-self.pause, block=False, scale=0.15, fg=(0, 1, 0, 1))
                        else:
                            self.sound(self.file_list_m[trial], volume=0.5)
                            self.write('+', duration=self.isi-self.pause, block=False, scale=0.15, fg=(1, 1, 1, 1))
                    #self.sleep(self.isi)
                    latencies = self.watchfor('space', self.isi)
                    if latencies:
                        f.write('yes\n')  # Space bar was pressed
                    else:
                        f.write('no\n')  # Space bar was not pressed
            self.write('You completed one run of the experiment.\n\n' + 
                       '\1gray\1[Press Space to continue]\2', duration='space', align='left', pos=(-0.5, 0), scale=0.05, fg=(1, 1, 1, 1))
        f.close()
    