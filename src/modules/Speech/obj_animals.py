from framework.latentmodule import LatentModule
from direct.gui.DirectGui import DirectButton
#from direct.gui.DirectGuiGlobals import RIDGE
from panda3d.core import NodePath
from panda3d.core import TextProperties, TextPropertiesManager
import random
import time
import itertools

class Main(LatentModule):
    def __init__(self):
        LatentModule.__init__(self)
        self.conditions = ['object', 'animal']
        
        # Load stimuli
        with open('studies/obj_animals/stimuli.txt', 'r') as f:
            self.stimuli = f.readlines()

        n_animals = 64
        n_objects = 464

        self.n_blocks = 4  # Divide the stimuli into this number of blocks

        animals_list = range(0, n_animals)
        objects_list = range(n_animals, n_animals + n_objects)

        animals_blocks = []
        objects_blocks = []
        self.stimuli_order = []  # This list contains the final indices
        self.av_type = []  # This list contains the stimulus type for each word (either 0 or 1, corresponding to auditory and visual, or vice versa)
        
        tmp_animals_1 = random.sample(animals_list, 32)  # Choose 32 random samples from animals
        tmp_animals_2 = list(set(animals_list) - set(tmp_animals_1))
        
        for k in range(self.n_blocks):
            if k % 2 == 0:
                tmp_animals = tmp_animals_1
            else:
                tmp_animals = tmp_animals_2
            random.shuffle(tmp_animals)
            animals_blocks.append(tmp_animals)
            
            tmp_objects = random.sample(objects_list, n_objects/self.n_blocks)
            objects_blocks.append(tmp_objects)
            objects_list = list(set(objects_list) - set(tmp_objects))
            
            tmp_animals_objects = animals_blocks[k] + objects_blocks[k]
            random.shuffle(tmp_animals_objects)
            # Make sure that there are no consecutive equal animals - shuffle until this is not the case
            max_repeats = max(len(list(v)) for g, v in itertools.groupby(tmp_animals_objects))
            while max_repeats > 1:
                random.shuffle(tmp_animals_objects)
                max_repeats = max(len(list(v)) for g, v in itertools.groupby(tmp_animals_objects))
            self.stimuli_order.append(tmp_animals_objects)

        # Flatten lists
        self.stimuli_order = [item for sublist in self.stimuli_order for item in sublist]
        self.target = [1 for k in range(1, n_animals + 1)] + [0 for k in range(1, n_objects + 1)]
        self.pause = 0.5
        self.score = 0  # Total score
        
    def run(self):
        self.implicit_markers = False
        base.win.setClearColor((0, 0, 0, 1))
        
        self.marker(0)  # Send one event to trigger the whole event sending process
        
        if self.training:
            self.stimuli_order = self.stimuli_order[:16]
            self.n_blocks = 1
            self.n_runs = 1
        
        if self.av_type == 'auditory':
            self.file_list = ['studies/obj_animals/stimuli/' + k.strip() + '_f.wav' for k in self.stimuli]
            for f in self.file_list:
                self.precache_sound(f)
        self.precache_sound('buzz.wav')
        self.precache_sound('beep.wav')
            
        # Define text properties
        tp_gray = TextProperties()
        tp_gray.setTextColor(0.5, 0.5, 0.5, 1)
        tpMgr = TextPropertiesManager.getGlobalPtr()
        tpMgr.setProperties("gray", tp_gray)
        
        # Show instructions
        if self.training:
            if self.av_type == 'visual':
                verb = 'see'
            else:
                verb = 'hear'
            self.write('This is a word association experiment.\nYou will complete several trials in this block.\n\n' + 
                       '\1gray\1[Press Space to continue]\2', fg=(1, 1, 1, 1), duration='space', align='left', pos=(-0.5, 0), scale=0.05)
            self.write('The experiment consists of two conditions.\nIn each trial, ' + 
                       'you will be prompted to perform\none of these two tasks:\n' +
                       '(1) touch a button on the screen,\n' + 
                       '(2) press the space bar.\n\n\1gray\1[Press Space to continue]\2', fg=(1, 1, 1, 1), duration='space', align='left', pos=(-0.5, 0), scale=0.05)
            self.write('In each trial, you will ' + verb + ' a word.\nWhen the word is an animal,\n' + 
                       'touch the button on the screen.\n\n\1gray\1[Press Space to continue]\2', fg=(1, 1, 1, 1), duration='space', align='left', pos=(-0.5, 0), scale=0.05)
            self.write('When the word is an object,\npress the space bar.\n\n\1gray\1[Press Space to continue]\2', fg=(1, 1, 1, 1), duration='space', align='left', pos=(-0.5, 0), scale=0.05)
            self.write('You will hear a beep for correct answers.\nYou will hear a buzz for incorrect answers.\n\n\1gray\1[Press Space to continue]\2', fg=(1, 1, 1, 1), duration='space', align='left', pos=(-0.5, 0), scale=0.05)
        self.write('When you are ready,\npress the space bar to begin.' + 
                   '\n\n\1gray\1[Press Space to continue]\2', fg=(1, 1, 1, 1), duration='space', align='left', pos=(-0.5, 0), scale=0.05)

        t = time.localtime()
        t_str = '-'.join([str(k) for k in [t.tm_year, t.tm_mon, t.tm_mday, t.tm_hour, t.tm_min, t.tm_sec]])
        f = open('studies/obj_animals/log/' + t_str + '.txt', 'w')
        f.write('Stimulus No.\tStimulus\tCategory\tButton position\tScore\n')
        self.sleep(5)
        
        counter = 0  # Needed for breaks between blocks
       
        for k in self.stimuli_order:

            # Short break
            if not self.training and counter in xrange(len(self.stimuli_order)/self.n_blocks/2, len(self.stimuli_order), len(self.stimuli_order)/self.n_blocks/2):
                self.write('Time for a short break.\n\n' + 
                          '\1gray\1[Press Space to continue]\2', fg=(1, 1, 1, 1), duration='space', align='left', pos=(-0.5, 0), scale=0.05)
                self.sleep(2)
            
            counter += 1
            
            # I have to calculate button positions in case the window size changed
            ar = base.getAspectRatio()
            button_frame = (-ar/9, ar/9, -1.0/4, 1.0/4)
            buttons = []
            for k1 in xrange(2, 7):
                    for k2 in xrange(4):
                        buttons.append((-ar + ar / 9 + k1 * ar / 4.5, 0, 1 - 1.0 / 4 - k2 / 2.0))
            # Delete middle buttons
            del buttons[5:7]
            del buttons[7:9]
            del buttons[9:11] 
            
            choice = random.randint(0, len(buttons) - 1)
            button = buttons[choice]
            f.write(str(k) + '\t' + self.stimuli[k].strip() + '\t' + self.conditions[self.target[k]] + '\t' + str(choice) + '\t')
            
            # Visual or auditory presentation
            if self.av_type == 'auditory':
                self.sound(self.file_list[k], volume=0.5)
                self.sleep(0.2)
                self.write('+', duration=self.isi-self.pause, block=False, scale=0.15, fg=(1, 1, 1, 1))  
            elif self.av_type == 'visual':
                self.sleep(0.2)
                self.write(self.stimuli[k], duration=self.isi-self.pause, block=False, scale=0.15, fg=(1, 1, 1, 1))
                
            self.marker(k + 10000)
            btn = DirectButton(frameSize=button_frame, pos=button, frameColor=(0.75, 0, 0, 1), borderWidth=(0.01, 0.01),
                               rolloverSound=None, clickSound=None, command=messenger.send, extraArgs=('button_pressed',))
          
            latencies = self.waitfor_multiple(['button_pressed', 'space'], self.isi)
            if not latencies:
                response = 'none'
                wait_time = self.pause
                self.sound('buzz.wav', volume=0.5)
            else:
                response = latencies[0]
                wait_time = self.pause + self.isi - latencies[1]
                if self.target[k] == 1 and response == 'button_pressed':  # Check if values in dictionary are not empty
                    self.score += int(100 * (self.isi - latencies[1]) / self.isi)
                    self.sound('beep.wav', volume=0.5)
                elif self.target[k] == 0 and response == 'space':
                    self.score += int(10 * (self.isi - latencies[1]) / self.isi)
                    self.sound('beep.wav', volume=0.5)
                elif (self.target[k] == 1 and response == 'space') or (self.target[k] == 0 and response == 'button_pressed'):
                    self.score -= 5
                    if self.score < 0:
                        self.score = 0
                    self.sound('buzz.wav', volume=0.5)
                 
            f.write(str(self.score) + '\n')
            try:
                btn.destroy()
            except:
                pass
            self.sleep(wait_time - 0.2)
                
        f.close()    
        if not self.training:    
            self.write('You successfully completed\none run of the experiment.\n\nThank you!', duration=5, align='left', pos=(-0.5, 0), scale=0.05, fg=(1, 1, 1, 1))
