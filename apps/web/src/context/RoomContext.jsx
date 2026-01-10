/* eslint-disable react-refresh/only-export-components */
import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { listRooms, createRoom as apiCreateRoom } from "../lib/tasksApi";

const RoomContext = createContext();

export function RoomProvider({ children }) {
  const [rooms, setRooms] = useState([]);
  const [currentRoomId, setCurrentRoomId] = useState(null);
  const [loading, setLoading] = useState(false);

  // Load rooms on mount
  const loadRooms = useCallback(async () => {
    setLoading(true);
    try {
      const data = await listRooms();
      setRooms(data);
      
      // If no current room, set to first room or team room
      setCurrentRoomId((prev) => {
        if (prev || data.length === 0) return prev;
        const teamRoom = data.find((r) => r.name?.toLowerCase() === "team");
        return teamRoom?.id || data[0]?.id || prev;
      });
    } catch (err) {
      console.error("Failed to load rooms:", err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadRooms();
  }, [loadRooms]);

  const createRoom = async (roomName) => {
    try {
      const newRoom = await apiCreateRoom(roomName);
      setRooms(prev => [newRoom, ...prev]);
      setCurrentRoomId(newRoom.room_id);
      return newRoom;
    } catch (err) {
      console.error("Failed to create room:", err);
      throw err;
    }
  };

  const switchRoom = (roomId) => {
    setCurrentRoomId(roomId);
  };

  return (
    <RoomContext.Provider
      value={{
        rooms,
        currentRoomId,
        loading,
        loadRooms,
        createRoom,
        switchRoom,
      }}
    >
      {children}
    </RoomContext.Provider>
  );
}

export function useRooms() {
  const context = useContext(RoomContext);
  if (!context) {
    throw new Error("useRooms must be used within RoomProvider");
  }
  return context;
}

export default RoomProvider;
