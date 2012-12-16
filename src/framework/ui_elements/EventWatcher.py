from direct.showbase import DirectObject
import framework.eventmarkers.eventmarkers
import time

class EventWatcher(DirectObject.DirectObject):
    """
    This class facilitates watching for events within a fixed time window.
    Checks for the global appearance of a given event in a particular time window and handles both timely responses and timeouts. 
    """
    def __init__(self,defaultevent="target-response",defaulthandler=None,handleduration=1.0,triggeronce=True):
        """
        Construct a new EventWatcher.
        * the eventtype determines the Panda3d event string which shall be watched by this EventWatcher
        * the defaulthandler is an optional handler which is called whenever the event occurs and no 
          specific handler is currently engaged via watch_for.
        * the handleduration is the default duration for which the watch_for() function will register
          the specifed handler
        * the triggeronce parameter controls whether by default the event handler passed to watch_for() may 
          only fire once or multiple times
        """
        self.defaultevent = defaultevent
        self.defaulthandler = defaulthandler
        self.handleduration = handleduration
        self.triggeronce = triggeronce
        
        self.handler = None
        self.timeouthandler = None
        self.expires_at = None
        self.expires_when_triggered = False
        
        #self.accept(eventtype,self._handleevent)
        framework.eventmarkers.eventmarkers.send_marker(213)
         
    def watch_for(self,handler=None,handleduration=None,timeouthandler=None,eventtype=None,triggeronce=None):
        """ 
        Set up a new handler for the event; the handler expires after the handleduration has passed,
        or after it has triggered once (if triggeronce is True).
        * handler is the function that shall be invoked when the event fires; if None, no handler is engaged 
                  The function is called as handler(event-type,trigger-time)
        * handleduration, if specified, is the duration for which the handler should be active; if unspecified,
          the default handleduration (passed at time of construction) is used
        * timeouthandler is an optional handler that gets called when the handler expires due to timeout
        * triggeronce can be used to make sure that a handler will automatically expire after it has been called once
          (if unspecified, the default value passed at construction time of the EventWatcher will be used)
          
        The previous handler may be replaced by calling watch_for again. If at the time of an event, 
        no handler is active, the defaulthandler (if present) will be called.
        """
        if eventtype is None:
            eventtype = self.defaultevent
        if handleduration is None:
            handleduration = self.handleduration
        if triggeronce is None:
            triggeronce = self.triggeronce

        if not (isinstance(eventtype,list) or isinstance(eventtype,tuple)):
            eventtype = [eventtype]
        for evtype in eventtype:            
            self.acceptOnce(evtype,self._handleevent,[evtype])
        print str(time.time()) + " now watching for any event in: " + str(eventtype)

        
        # register a new handler (replacing the old one, if necessary) 
        self.handler = handler
        self.timeouthandler = timeouthandler
        self.expires_at = time.time() + handleduration
        self.expires_when_triggered = triggeronce
        framework.eventmarkers.eventmarkers.send_marker(214)
        taskMgr.doMethodLater(handleduration, self._trigger_timeout, 'EventWatcher.trigger_timeout()')

    def _handleevent(self,evtype):
        t = time.time()
        self.timeouthandler = None
        if self.handler is not None:
            if self.expires_at > t:
                # pressed in time
                framework.eventmarkers.eventmarkers.send_marker(217)
                self.handler(evtype,t)
                if self.expires_when_triggered:
                    # now expires
                    self.handler = None
            else:
                # pressed outside the valid time
                self.handler = None
                if self.defaulthandler is not None:
                    framework.eventmarkers.eventmarkers.send_marker(218)
                    self.defaulthandler(evtype,t)
                else:
                    framework.eventmarkers.eventmarkers.send_marker(219)
        else:
            # pressed without a handler registered
            if self.defaulthandler is not None:
                framework.eventmarkers.eventmarkers.send_marker(218)
                self.defaulthandler(evtype,t)
            else:
                framework.eventmarkers.eventmarkers.send_marker(219)

    def destroy(self):
        self.ignoreAll()

    def _trigger_timeout(self,task):
        if time.time() < self.expires_at:
            return task.cont
        else:
            if self.timeouthandler is not None:
                framework.eventmarkers.eventmarkers.send_marker(215)
                self.timeouthandler()
            else:
                framework.eventmarkers.eventmarkers.send_marker(216)
            return task.done
