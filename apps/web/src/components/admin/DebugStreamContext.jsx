import React, { createContext, useContext, useEffect, useState } from "react";
import { subscribeDebugStream } from "./DebugStreamBus";

const DebugStreamContext = createContext({
  events: [],
  clear: () => {},
});

export const DebugStreamProvider = ({ children }) => {
  const [events, setEvents] = useState([]);

  useEffect(() => {
    const unsubscribe = subscribeDebugStream((evt) => {
      setEvents((prev) => {
        const next = [...prev, { ...evt, ts: Date.now() }];
        if (next.length > 50) {
          next.shift();
        }
        return next;
      });
    });
    return () => unsubscribe();
  }, []);

  const clear = () => setEvents([]);

  return (
    <DebugStreamContext.Provider value={{ events, clear }}>
      {children}
    </DebugStreamContext.Provider>
  );
};

export const useDebugStream = () => useContext(DebugStreamContext);
