import time


class AsyncResultTimeout(Exception):
    """an exception that represents an :class:`AsyncResult` that has timed out"""
    pass

class AsyncResult(object):
    """*AsyncResult* represents a computation that occurs in the background and
    will eventually have a result. Use the :attr:`async_value` property to access the 
    result (which will block if the result has not yet arrived).
    
    This object can to some extent transparently mimic the value that it holds;
    however, consider this a somewhat brittle convenience feature -- the proper way
    is to call .async_value to obtain the resulting value.
    """
    __slots__ = ["_conn", "_is_ready", "_is_exc", "_callbacks", "_obj", "_ttl"]
    def __init__(self, conn):
        self._conn = conn
        self._is_ready = False
        self._is_exc = None
        self._obj = None
        self._callbacks = []
        self._ttl = None
    
    def async_assign(self, is_exc, obj):
        """Assigns the value to the AsyncResults; this is a callback issued by the 
        connection."""
        if self.async_expired:
            return
        self._is_exc = is_exc
        self._obj = obj
        self._is_ready = True
        for cb in self._callbacks:
            cb(self)
        del self._callbacks[:]

    def async_wait(self):
        """Waits for the result to arrive. If the AsyncResult object has an
        expiry set, and the result did not arrive within that timeout,
        an :class:`AsyncResultTimeout` exception is raised"""
        if self._is_ready:
            return
        if self._ttl is None:
            while not self._is_ready:
                self._conn.serve()
        else:
            while True:
                timeout = self._ttl - time.time()
                self._conn.poll(timeout = max(timeout, 0))
                if self._is_ready:
                    break
                if timeout <= 0:
                    raise AsyncResultTimeout("result expired")
    
    def async_add_callback(self, func):
        """Adds a callback to be invoked when the result arrives. The callback 
        function takes a single argument, which is the current AsyncResult
        (``self``). If the result has already arrived, the function is invoked
        immediately.
        
        :param func: the callback function to add
        """
        if self._is_ready:
            func(self)
        else:
            self._callbacks.append(func)
            
    def async_set_expiry(self, timeout):
        """Sets the expiry time (in seconds, relative to now) or ``None`` for
        unlimited time
        
        :param timeout: the expiry time in seconds or ``None``
        """
        if timeout is None:
            self._ttl = None
        else:
            self._ttl = time.time() + timeout

    @property
    def async_ready(self):
        """Indicates whether the result has arrived"""
        if self.async_expired:
            return False
        if not self._is_ready:
            self._conn.poll_all()
        return self._is_ready
    
    @property
    def async_error(self):
        """Indicates whether the returned result is an exception"""
        if self.async_ready:
            return self._is_exc
        return False
    
    @property
    def async_expired(self):
        """Indicates whether the AsyncResult has expired"""
        if self._is_ready or self._ttl is None:
            return False
        else:
            return time.time() > self._ttl

    @property
    def async_value(self):
        """Returns the result of the operation. If the result has not yet
        arrived, accessing this property will wait for it. If the result does
        not arrive before the expiry time elapses, :class:`AsyncResultTimeout` 
        is raised. If the returned result is an exception, it will be raised 
        here. Otherwise, the result is returned directly.
        """
        self.async_wait()
        if self._is_exc:
            raise self._obj
        else:
            return self._obj


    # === a bit of magic: an AsyncResult can to some extent masquerade as a lazy proxy of its value ===
    # the list comes from the article A Guide to Python's Magic Methods (version 1.13)
    
    def __getattr__(self,name):
        return getattr(self.async_value,name)
        
    def __setattr__(self,name,value):
        if not name in self.__slots__:         
            return self.async_value.__setattr__(name,value)
        else:
            return object.__setattr__(self,name,value)
    
    def __delattr__(self,name,value):
        return self.async_value.__delattr__(name,value)

    def __call__(self, *args, **kwargs):
        return self.async_value.__call__(*args,**kwargs)

    def __cmp__(self, other):
        return self.async_value.__cmp__(other)

    def __pos__(self):
        return self.async_value.__pos__()
    def __neg__(self):
        return self.async_value.__neg__()
    def __abs__(self):
        return self.async_value.__abs__()
    def __invert__(self):
        return self.async_value.__invert__()

    def __add__(self, other):
        return self.async_value.__add__(other)
    def __sub__(self, other):
        return self.async_value.__sub__(other)
    def __mul__(self, other):
        return self.async_value.__mul__(other)
    def __floordiv__(self, other):
        return self.async_value.__floordiv__(other)
    def __div__(self, other):
        return self.async_value.__div__(other)
    def __truediv__(self, other):
        return self.async_value.__truediv__(other)
    def __mod__(self, other):
        return self.async_value.__mod__(other)
    def __divmod__(self, other):
        return self.async_value.__divmod__(other)
    def __pow__(self, other):
        return self.async_value.__pow__(other)
    def __lshift__(self, other):
        return self.async_value.__lshift__(other)
    def __rshift__(self, other):
        return self.async_value.__rshift__(other)
    def __and__(self, other):
        return self.async_value.__and__(other)
    def __or__(self, other):
        return self.async_value.__or__(other)
    def __xor__(self, other):
        return self.async_value.__xor__(other)

    def __radd__(self, other):
        return self.async_value.__radd__(other)
    def __rsub__(self, other):
        return self.async_value.__rsub__(other)
    def __rmul__(self, other):
        return self.async_value.__rmul__(other)
    def __rfloordiv__(self, other):
        return self.async_value.__rfloordiv__(other)
    def __rdiv__(self, other):
        return self.async_value.__rdiv__(other)
    def __rtruediv__(self, other):
        return self.async_value.__rtruediv__(other)
    def __rmod__(self, other):
        return self.async_value.__rmod__(other)
    def __rdivmod__(self, other):
        return self.async_value.__rdivmod__(other)
    def __rpow__(self, other):
        return self.async_value.__rpow__(other)
    def __rlshift__(self, other):
        return self.async_value.__rlshift__(other)
    def __rrshift__(self, other):
        return self.async_value.__rrshift__(other)
    def __rand__(self, other):
        return self.async_value.__rand__(other)
    def __ror__(self, other):
        return self.async_value.__ror__(other)
    def __rxor__(self, other):
        return self.async_value.__rxor__(other)

    def __iadd__(self, other):
        return self.async_value.__iadd__(other)
    def __isub__(self, other):
        return self.async_value.__isub__(other)
    def __imul__(self, other):
        return self.async_value.__imul__(other)
    def __ifloordiv__(self,other):
        return self.async_value.__ifloordiv__(other)
    def __idiv__(self,other):
        return self.async_value.__idiv__(other)
    def __itruediv__(self, other):
        return self.async_value.__itruediv__(other)
    def __imod__(self,other):
        return self.async_value.__imod__(other)
    def __idivmod__(self,other):
        return self.async_value.__idivmod__(other)
    def __ipow__(self, other):
        return self.async_value.__ipow__(other)
    def __ilshift__(self,other):
        return self.async_value.__ilshift__(other)
    def __irshift__(self,other):
        return self.async_value.__irshift__(other)
    def __iand__(self, other):
        return self.async_value.__iand__(other)
    def __ior__(self, other):
        return self.async_value.__ior__(other)
    def __ixor__(self, other):
        return self.async_value.__ixor__(other)

    def __int__(self):
        return self.async_value.__int__()
    def __long__(self):
        return self.async_value.__long__()
    def __float__(self):
        return self.async_value.__float__()
    def __complex__(self):
        return self.async_value.__complex__()
    def __oct__(self):
        return self.async_value.__oct__()
    def __index__(self):
        return self.async_value.__index__()
    def __trunc__(self):
        return self.async_value.__trunc__()
    def __coerce__(self, other):
        return self.async_value.__coerce__(other)

    def __str__(self):
        return self.async_value.__str__()
    def __repr__(self):
        return self.async_value.__repr__()
    def __unicode__(self):
        return self.async_value.__unicode__()
    def __hash__(self):
        return self.async_value.__hash__()
    def __nonzero__(self):
        return self.async_value.__nonzero__()

    def __len__(self):
        return self.async_value.__len__()
    def __getitem__(self,key):
        return self.async_value.__getitem__(key)
    def __setitem__(self,key,value):
        return self.async_value.__setitem__(key,value)
    def __delitem__(self,key):
        return self.async_value.__delitem__(key)
    def __iter__(self):
        return self.async_value.__iter__()
    def __reversed__(self,key,value):
        return self.async_value.__reversed__(key,value)
    def __contains__(self,item):
        return self.async_value.__contains__(item)
    def __concat__(self,other):
        return self.async_value.__concat__(other)

    def __instancecheck__(self,instance):
        return self.async_value.__instancecheck__(instance)
    def __subclasscheck__(self,subclass):
        return self.async_value.__subclasscheck__(subclass)

    def __enter__(self):
        return self.async_value.__enter__()
    def __exit__(self,exception_type,exception_value,traceback):
        return self.async_value.__exit__(exception_type,exception_value,traceback)
        
    def __reduce_ex__(self, proto):
        return self.async_value.__reduce_ex__(proto)
        