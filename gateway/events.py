"""Event bus used by gateway services."""
import asyncio
import logging
from typing import Dict, List, Callable, Any, Optional
from collections import defaultdict
from .protocol import EventType, EventMessage

logger = logging.getLogger("Gateway.Events")


class EventEmitter:
    """Async event emitter with listener registry and bounded history."""
    
    def __init__(self):
        self._listeners: Dict[EventType, List[Callable]] = defaultdict(list)
        self._seq_counter = 0
        self._event_history: List[EventMessage] = []
        self._max_history = 1000
        
    def on(self, event: EventType, handler: Callable) -> None:
        """Register a listener for an event."""
        if handler not in self._listeners[event]:
            self._listeners[event].append(handler)
            logger.debug(f"Registered handler for event: {event}")
    
    def off(self, event: EventType, handler: Callable) -> None:
        """Unregister a listener."""
        if handler in self._listeners[event]:
            self._listeners[event].remove(handler)
            logger.debug(f"Unregistered handler for event: {event}")
    
    def once(self, event: EventType, handler: Callable) -> None:
        """Register a listener that runs once."""
        async def wrapper(*args, **kwargs):
            await handler(*args, **kwargs)
            self.off(event, wrapper)
        self.on(event, wrapper)
    
    async def emit(self, event: EventType, payload: Dict[str, Any]) -> None:
        """Emit event to all listeners."""
        self._seq_counter += 1
        event_msg = EventMessage(
            event=event,
            payload=payload,
            seq=self._seq_counter
        )
        
        # Keep bounded event history for diagnostics.
        self._event_history.append(event_msg)
        if len(self._event_history) > self._max_history:
            self._event_history = self._event_history[-self._max_history:]
        
        # Dispatch handlers.
        handlers = self._listeners.get(event, [])
        if handlers:
            logger.debug(f"Emitting event {event} to {len(handlers)} handlers")
            tasks = []
            for handler in handlers:
                try:
                    if asyncio.iscoroutinefunction(handler):
                        tasks.append(handler(event_msg))
                    else:
                        handler(event_msg)
                except Exception as e:
                    logger.error(f"Error in event handler for {event}: {e}")
            
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
        else:
            logger.debug(f"No handlers for event: {event}")
    
    def get_history(self, event: Optional[EventType] = None, limit: int = 100) -> List[EventMessage]:
        """Return event history, optionally filtered by event type."""
        if event:
            filtered = [e for e in self._event_history if e.event == event]
            return filtered[-limit:]
        return self._event_history[-limit:]
    
    def clear_listeners(self, event: Optional[EventType] = None) -> None:
        """Clear listeners for one event or all events."""
        if event:
            self._listeners[event].clear()
        else:
            self._listeners.clear()
