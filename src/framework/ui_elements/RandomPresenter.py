from MessagePresenter import MessagePresenter
import random

class RandomPresenter(MessagePresenter):
    """
    A simple wrapper/proxy around a presenter which replaces previously defined messages by a random selection of 
    pre-loaded messages. For example, the message "target" can be replaced by a random selection of a set of 
    target messages.
    """
        
    def __init__(self,
                 wrappresenter=None,        # the backend presenter to wrap  
                 messages={'target':['sample-target0,sample-target1,sample-target2'],'nontarget':['nt0','nt1']}, 
                                            # the message map; each of the keys in this dictionary will be  
                                            # replaced upon submit() by a random choice out of the corresponding value list
                 *args,**kwargs 
                 ):
        
        MessagePresenter.__init__(self,*args,**kwargs)
        self.wrappresenter = wrappresenter
        self.messages = messages

    def submit(self,message,lockduration=None,clearafter=None):
        """Submit a new message."""
        self.marker(220)
        if self.messages.has_key(message):
            msg_idx = [i for i,x in enumerate(self.messages.iterkeys()) if x == message]
            self.marker(10000+msg_idx[0])
            item_idx = random.choice(range(len(self.messages[message])))
            self.marker(20000+item_idx)
            message = self.messages[message][item_idx]
        print "chosen message: ",message,"(set size: ",len(self.messages),")"
        return self.wrappresenter.submit(message,lockduration,clearafter)

    def clear(self):
        """Clear the image."""
        self.wrappresenter.clear()
    
    def destroy(self):
        """Remove the presenter."""
        self.wrappresenter.destroy()

    def precache(self,message):
        """Pre-cache a message."""
        if self.messages.has_key(message):
            for m in self.messages[message]:
                self.wrappresenter.precache(m)
        else:
            self.wrappresenter.precache(message)

    def unlock(self):
        """Manually unlock the presenter (always succeeds)."""
        self.wrappresenter.unlock()
