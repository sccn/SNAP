# ===========================================================================
# Base class for all modules that contain latent code (i.e. code that may call
# time-consumption functions, such as sleep()).
# ===========================================================================

import framework.tickmodule
import framework.basicstimuli
import threading, time, traceback

class LatentModule(framework.tickmodule.TickModule, framework.basicstimuli.BasicStimuli):
    """
    Derive from this class to implement your own module with latent code, by overriding 
    the run() function. The only parts in your code that should consume significant amounts 
    of time are the calls to explicit time-consumption functions (see below), such as sleep().
    The module convenience.py also contains a batch of functions that may consume time.
    
    Note that any of these functions may throw a ModuleCancelled exception, in which case your function
    needs to clean all resources from the screen, audio buffers (and event handlers) and exit as soon
    as possible (ideally instantly). The most convenient way to accomplish this is using the try/finally
    idiom (where you may have a single try/finally block around your function which clears all resources, 
    or multiple, perhaps nested blocks around individual resource allocations).
    
    Your function typically sets up objects to be rendered, animations, and appropriate event handlers,
    and then enters a sleep call until the next action needs to be taken. The only functions
    that execute during sleep are the periodic tick function, any registered event handlers, 
    scene rendering and any tasks that have been scheduled either via the task manager of Panda3d or 
    the spawn() function. The sleep call may be terminated early by calling resume() from any of 
    those functions.
    
    You can implement all code in the tick() function (e.g. simple games), or you can set up an 
    elaborate hierarchy of event handlers, sequences and intervals (as usual in Panda3d), or you
    can implement the majority of code as "regular code" with interleaved time-consumption functions,
    or mix these styles.
    """

    def __init__(self,
                 default_tick=None,             # the tick function that is running whenever no current tick function is specified
                 make_up_for_lost_time=True,    # whether time lost during a sleep(), e.g., due to jitter, will be compensated over successive sleep's
                 max_compensated_time=0.5,      # the maximum amount of lost time prior to any sleep() call that will be compensated for
                 max_inter_frame_interval=0.5): # the maximum frame time during normal operation that is not considered a hickup, in seconds
        """
        Construct a new LatentModule; a default tick function (called at every frame) may be specified here.
        This is the place to assign default values and arguments to all variables. Ideally you should defer any processing
        of these variables (such as loading text files) to the beginning of the run() function, since the default values
        may be overridden by the experimenter or config files after the module has been initialized.
        """
        framework.basicstimuli.BasicStimuli.__init__(self)

        self._thread = None             # the internal runner thread; None if not running
        self._resumecond = threading.Condition(framework.tickmodule.shared_lock) # condition variable that signals that the sleep period is over
        self._cancelled = False         # signals whether cancel() has been invoked (i.e. that run() shall terminate at the next opportunity)

        now = time.time()
        self._resumeat = now            # the point in time when the currently running time-consumption function should resume (if any)
        self._exectime = now            # the time point when the last time-consumption function was invoked
        self._lasttick = now            # the time point of the last tick()
        self._frametime = 1/60.0        # initial guess of time time between frames (updated every frame)
        self._make_up_for_lost_time = make_up_for_lost_time         # whether time lost during a sleep(), e.g., due to jitter, will be compensated over successive sleep's
        self._max_compensated_time = max_compensated_time           # the maximum amount of lost time prior to any sleep() call that will be compensated for
        self._max_inter_frame_interval = max_inter_frame_interval   # the maximum reasonable frame time during normal operation, in seconds

        self._cur_tick = None             # the tick function that is currently in place
        self._default_tick = default_tick # the tick function that is running whenever no current tick function is specified
        
        self._subtasks = []             # optional list of any semi-parallel sub-tasks; tick and cancel are propagated down to them
        self._messages = []             # queue of messages to be sent off at the next tick
        self._to_destroy = []           # list of objects to .destroy() upon cancel


    # ======================
    # === Core Interface ===
    # ======================

    def run(self):
        """
        Override this function with your code.
        * Expect to receive a ModuleCancelled exception during any call to a time-consumption function (like sleep());
          this happens when the experimenter decides to cancel your current run.
        * Consider using try/finally in your run() function to clean up any on-screen (or audio) resources when the
          module is cancelled. This is especially true in the advanced use case of implementing parallel sub-tasks that
          are intended to be cancelled at some point by the main task.
        """


    def launch(self,newtask,inherit_timing_parameters=True):
        """
        Launch a new latent sub-task that will be executed interleaved ("semi-parallel") with the current task.
        start(), cancel() and tick() will be executed for it automatically as appropriate.
        """
        if inherit_timing_parameters:
            newtask._make_up_for_lost_time = self._make_up_for_lost_time
            newtask._max_compensated_time = self._max_compensated_time
            newtask._max_inter_frame_interval = self._max_inter_frame_interval
        newtask.start()
        self._subtasks.append(newtask)
        return newtask


    # ====================================================================================
    # === Functions that wait for things to happen (a.k.a. time-consumption functions) ===
    # ====================================================================================

    def sleep(self,duration=100000,cur_tick=None):
        """
        Sleep for a number of seconds; optionally execute some tick function at every frame.
        Event handlers may fire during this time, and content is rendered every frame.
        """
        self._exectime = time.time()
        if self._make_up_for_lost_time and abs(self._resumeat - self._exectime) < self._max_compensated_time:
            self._resumeat = self._resumeat + duration
        else:
            self._resumeat = self._exectime + duration

        self._cur_tick = cur_tick
        if self._cancelled:
            # make sure that run() terminates
            raise self.ModuleCancelled
        self._resumecond.wait(self._resumeat - self._exectime)
        if self._cancelled:
            # make sure that run() terminates
            raise self.ModuleCancelled


    def waitfor(self,eventid,duration=100000,cur_tick=None):            
        """
        Wait until a specified event occurs or a number of seconds has passed;
        optionally execute some tick function at every frame.
        
        Returns None if no event has happened and otherwise the time when the 
        event occurred (relative to the beginning of the wait period).
        """
        # register the event handler(s)
        self._events_received = []
        self._times_received = []

        try:
            self.accept(eventid,self._on_wait_event,[eventid])

            # call sleep
            if self.implicit_markers:
                self.marker(228)
            self.sleep(duration,cur_tick)

        finally:
            self.ignore(eventid)

        # wrap up results
        if len(self._times_received) > 0:
            return self._times_received[0]
        else:
            return None


    def waitfor_multiple(self,eventids,duration=100000,cur_tick=None):            
        """
        Wait until any out of a list of events occurs or a number of seconds
        has passed; optionally execute some tick function at every frame.
        
        Returns None if no event has happened and otherwise a tuple of the 
        id of the event that happened first and the time when it occurred
        (relative to the beginning of the wait period).
        """
        # register the event handler(s)
        self._events_received = []
        self._times_received = []
        if eventids.__class__ is str:
            eventids = [eventids]

        try:
            for eventid in eventids:
                self.accept(eventid,self._on_wait_event,[eventid])

            # call sleep
            if self.implicit_markers:
                self.marker(228)
            self.sleep(duration,cur_tick)

        finally:
            for eventid in eventids:
                self.ignore(eventid)

        # wrap up results
        if len(self._times_received) > 0:
            return (self._events_received[0],self._times_received[0])
        else:
            return None


    def watchfor(self,eventid,duration=100000,cur_tick=None):            
        """
        Sleep for a number of seconds and record the times of occurrence
        of an event; optionally execute some tick function at every frame. 

        Returns a list of times at which the event occurred (relative to the 
        beginning of the watch period), or an empty list if it did not occur.
        """
        try:
            self._measuretime = time.time()
            # register an event handler
            self._received_dict = {eventid:[]}
            self._events_received = []
            self.accept(eventid,self._on_record_event,[eventid])

            # call sleep
            if self.implicit_markers:
                self.marker(228)
            self.sleep(duration,cur_tick)
            
        finally:
            # unregister the handler
            self.ignore(eventid)

        return self._received_dict[eventid]
    
    
    def watchfor_multiple(self,eventids,duration=100000,cur_tick=None,list_only=False):            
        """
        Sleep for a number of seconds and record the types and times of
        occurrence of specified events; optionally execute some tick function at  
        every frame. Event-handlers may fire during this time, and content is 
        rendered every frame.
        
        Returns a dictionary from event type to a list of times at which the event 
        occurred (relative to the beginning of the watch period). If list_only is given
        as true, instead a list of event codes in order of appearance is returned 
        """
        try:
            self._measuretime = time.time()
            # register event handlers and reset the dict
            self._received_dict = {}
            self._events_received = []
            for eventid in eventids:
                self._received_dict[eventid] = [] 
                self.accept(eventid,self._on_record_event,[eventid])

            # call sleep
            if self.implicit_markers:
                self.marker(228)
            self.sleep(duration,cur_tick)
            
        finally:
            # unregister the handlers
            for eventid in eventids:             
                self.ignore(eventid)

        if list_only:
            return self._events_received
        else:
            return self._received_dict


    def watchfor_multiple_begin(self,eventids):            
        """
        Begin watching for multiple events. The results are obtained by
        calling results = watchfor_multiple_end().
        
        The general usage pattern is:
        
        h = watchfor_multiple_begin(['event1','event2'])
        # ... do something ...
        results = watchfor_multiple_end(h);
        """
        # register event handlers and reset the dict
        self._measuretime = time.time()        
        self._received_dict = {}
        self._events_received = []
        for eventid in eventids:
            self._received_dict[eventid] = [] 
            self.accept(eventid,self._on_record_event,[eventid])
        if self.implicit_markers:
            self.marker(228)
        return eventids


    def watchfor_multiple_end(self,handle,list_only=False):            
        """
        Returns a dictionary from event type to a list of times at which the event
        occurred (relative to the beginning of the watch period). If list_only is given
        as true, instead a list of event codes in order of appearance is returned.
        """

        # unregister the handlers
        for eventid in handle:             
            self.ignore(eventid)
        if list_only:
            return self._events_received
        else:
            return self._received_dict


    def resume(self):
        """
        Resume from a time-consumption function, e.g., in response to some event.
        """
        self._resumeat = time.time()


    def consumed_duration(self):
        """
        The amount of time that has been consumed since the most recent time-consumption function was entered.
        """
        return time.time() - self._exectime
    

    # ==============================================
    # === advanced functions for complex modules ===
    # ==============================================

    def send_message(self,msg):
        """
        Convenience function for sending messages.
        """
        self._messages.append(msg)


    def prune(self):
        """
        Optionally release any large cached resources (e.g. textures) to make space for the next module.
        """

    # ==================================================
    # === Implementation of the TickModule interface ===
    # ==================================================

    def start(self):
        """
        Implementation of the start() interface, see TickModule.
        """
        try:
            framework.tickmodule.shared_lock.acquire()
            #framework.tickmodule.engine_lock.acquire()
            if self._thread is None:
                # create the runner thread and launch it
                self._thread = threading.Thread(target=self._run_wrap)
                self._thread.daemon = True
                self._thread.start()
                self._cancelled = False
                self._resumeat = time.time()
                # make sure that the sub-tasks are clean
                self._subtasks = []  
        finally:
            #framework.tickmodule.engine_lock.release()
            framework.tickmodule.shared_lock.release()
            
    
    def cancel(self):
        """
        Implementation of the cancel() interface, see TickModule.
        """
        # first cancel all sub-tasks
        for t in self._subtasks:
            t.cancel()
        self._subtasks = []

        framework.tickmodule.shared_lock.acquire()
        #framework.tickmodule.engine_lock.acquire()
                
        # then cancel the main thread
        if self._thread is not None:
            thread = self._thread
            # set the cancellation flag and notify the thread
            self._cancelled = True
            self._resumecond.notify()
            # wait until the thread has terminated
            #framework.tickmodule.engine_lock.release()
            framework.tickmodule.shared_lock.release()
            self._thread = None
        else:
            #framework.tickmodule.engine_lock.release()
            framework.tickmodule.shared_lock.release()

        # finally destroy all objects in self._to_destroy (in reverse order)
        self._to_destroy.reverse()
        for e in self._to_destroy:
            try:
                e.destroy()
            except:
                pass
            

    def tick(self):
        """
        Implementation of the tick() interface, see TickModule.
        """
        try:
            framework.tickmodule.shared_lock.acquire()
            #framework.tickmodule.engine_lock.acquire()
            
            # determine the inter-frame time delta (if it's not a hickup)
            now = time.time()
            delta = now - self._lasttick
            if delta < self._max_inter_frame_interval:
                self._frametime = delta
            self._lasttick = now
            
            # send all queued messages
            for msg in self._messages:
                messenger.send(msg)
            self._messages = []            
                        
            # if we are closer to the frame at which we should resume than the one before, end the sleep period 
            if now > self._resumeat - self._frametime/2:
                # time-consumption function may finish now
                self._resumecond.notify()
            elif self._cur_tick is not None:
                # invoke current tick function
                if self._cur_tick(delta) is False:
                    self.resume()
            elif self._default_tick is not None:
                # invoke default tick function
                if self._default_tick(delta) is False:
                    self.resume()
                
            # propagate tick to sub-tasks    
            for t in self._subtasks[:]:
                if not t.is_alive():
                    # optimization: remove from subtasks if not alive anymore
                    self._subtasks.remove(t)
                else:
                    # invoke tick
                    t.tick()

        except Exception as inst:
            print "Exception during tick():"
            print inst
            traceback.print_exc()
            raise
        finally:
            #framework.tickmodule.engine_lock.release()
            framework.tickmodule.shared_lock.release()
        
    
    # ========================
    # === Internal Helpers ===
    # ========================

    def is_alive(self):
        """ Check whether the current module is (still) running."""
        return self._thread is not None    


    class ModuleCancelled(Exception):
        """
        Internal exception used to cancel the run() function from within
        a time-consumption function.
        """
        pass

        
    def _run_wrap(self):
        """
        Internal wrapper around the run function; executed in a separate thread.
        """
        try:
            # acquire the lock (will only be unlocked from within or after run())
            framework.tickmodule.shared_lock.acquire()
            #framework.tickmodule.engine_lock.acquire()
            self.run()
        except self.ModuleCancelled:
            # the ModuleCancelled exception is used to forcibly exit the run() funcion 
            pass
        except Exception,e:
            print "Exception during run():"
            print e
            traceback.print_exc()
        finally:
            # make sure that we release the lock and reset the state
            self._thread = None
            #framework.tickmodule.engine_lock.release()
            framework.tickmodule.shared_lock.release()

        

    def _on_wait_event(self,eventid):
        """
        Internal event handler for waitfor (triggers resume).
        """
        self._times_received.append(time.time()-self._exectime)
        self.marker(229)
        self._events_received.append(eventid)
        self.resume()

    
    def _on_record_event(self,eventid):
        """
        Internal event handler for watchfor(_multiple).
        """
        self._received_dict[eventid].append(time.time()-self._measuretime)
        idx = [i for i,x in enumerate(self._received_dict.iterkeys()) if x == eventid]
        self.marker(230+idx[0])
        self._events_received.append(eventid)
