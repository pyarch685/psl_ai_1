import { useState, createContext, useContext } from 'react';
import { Button } from '@/components/ui/button';
import { Volume2, VolumeX } from 'lucide-react';

interface SoundContextType {
  soundEnabled: boolean;
  toggleSound: () => void;
}

const SoundContext = createContext<SoundContextType>({
  soundEnabled: true,
  toggleSound: () => {},
});

export const useSoundContext = () => useContext(SoundContext);

export const SoundProvider = ({ children }: { children: React.ReactNode }) => {
  const [soundEnabled, setSoundEnabled] = useState(true);

  const toggleSound = () => setSoundEnabled(!soundEnabled);

  return (
    <SoundContext.Provider value={{ soundEnabled, toggleSound }}>
      {children}
    </SoundContext.Provider>
  );
};

export const SoundToggle = () => {
  const { soundEnabled, toggleSound } = useSoundContext();

  return (
    <Button
      variant="outline"
      size="icon"
      onClick={toggleSound}
      className="fixed top-4 right-4 z-50 bg-card/80 backdrop-blur-sm border-secondary/50 hover:bg-secondary/20"
    >
      {soundEnabled ? (
        <Volume2 className="h-5 w-5 text-secondary" />
      ) : (
        <VolumeX className="h-5 w-5 text-muted-foreground" />
      )}
    </Button>
  );
};
