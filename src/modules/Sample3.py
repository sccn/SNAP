from framework.latentmodule import LatentModule
import random
import time

class Main(LatentModule):
    def __init__(self):
        LatentModule.__init__(self)
        
        # set defaults for some configurable parameters:
        self.speed = 2

    def run(self):
        self.write('In the next part, please hit the A key whenever the ball hits the ground!\nSpace when ready.','space')
        watcher = self.watchfor_multiple_begin(['a'])
        
        vel = [self.speed,0]    # velocity
        pos = [-0.7,0.7]        # position
        
        ball = self.picture('ball.png',duration=10000,scale=0.03,pos=pos,block=False)
        now = time.time()
        t_end = now + 20
        while True:
            # calc amount of time passed
            dt = time.time() - now            
            now = time.time()
            if now > t_end:
                break
            
            # move the ball
            pos[0] += vel[0] * dt
            pos[1] += vel[1] * dt
            ball.setPos(pos[0],0,pos[1])
            # decelerate the ball and apply gravity
            vel[0] = vel[0]*0.98**dt
            vel[1] = vel[1]*0.98**dt - 2*dt
            # bounce
            if abs(pos[0]) > base.getAspectRatio():
                vel[0] = abs(vel[0]) * (-1 if pos[0]>0 else +1)
            if abs(pos[1]) > 1:
                vel[1] = abs(vel[1]) * (-1 if pos[1]>0 else +1)
            
            self.sleep(0.01)
        ball.destroy()
        
        results = self.watchfor_multiple_end(watcher)
        self.write('You pressed the A key at the following times:\n%s\n. Press space to end the experiment.' % str(results['a']),'space')
        self.write('You have successfully completed the experiment!')
