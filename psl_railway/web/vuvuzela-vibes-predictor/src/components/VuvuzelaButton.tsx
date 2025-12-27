import { useState, useRef } from 'react';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';

interface VuvuzelaButtonProps {
  onClick: () => void;
  children: React.ReactNode;
  className?: string;
  disabled?: boolean;
  isLoading?: boolean;
}

export const VuvuzelaButton = ({ 
  onClick, 
  children, 
  className,
  disabled,
  isLoading 
}: VuvuzelaButtonProps) => {
  const [isBlasting, setIsBlasting] = useState(false);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  const handleClick = () => {
    if (disabled || isLoading) return;
    
    setIsBlasting(true);
    
    // Play vuvuzela sound
    if (!audioRef.current) {
      audioRef.current = new Audio();
      // Using a simple horn sound that's widely available
      audioRef.current.src = 'data:audio/wav;base64,UklGRnoGAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YQoGAACBhYqFbF1fdH2Onq+3vL7Axse/t7KnmYx9bmFUTEdIT1pgb36OnaaxubvBw8K9uLKlmYx+cGNWTEVBQ0tXZHN/jZuosbm9wMHAu7WuoZOGd2pcUEdBPUBIU2JwfYuZpq+3u77AwL23sKSXiXtqXFFIQT1AS1hldIGOm6avtbi9v7+7trGlmIp8bF9TSUNAQklWZHKAjpuorbW5vL6/vbizq5+Ri35uYVRLRUJFTVlldoOQnaqxtbi8vb28uLOrn5KFd2pgVUtFQkVNWGV1go+cqLC1uLu9vby4s6yfl4l7bF9VTEZDRk5aZnaDkJ2qsLW4ury8u7ezq5+Th3ltYFVMRkRHTlpmdn+Mnaivsra5uru7uLWvpJiLfW9hVk1IRUhQXGl2g4+bprC1ubi6uri1sKiekod5a15UTkpHTVVfandIe4aRm6SssbW4urq3tLCon5SIem1fVU9KR0tTXWl1gYuVnqaqsba3t7a0sayknJKGenJkWE9LSUxSXGZweYKLlJqjqa6ys7S0s7CsqKGYjYF0Z1tRT0tNUlxkaHN8hIuSmJ+lqa2wsLGwr62poJeNgXRoXlRQTU9TW2FpcHqChYmPl52jqKqsrq2tq6ejnpWMgXVqYFlUUVFUWV5kaG93fICEiY6TmZ2hpKampaaloZyXj4d+dGxlXllWVFVYXGJmam9zdnp+g4eKjo+RlJaYmZiXlZOQjomEfnh0cG1rammam6WrrK2rqKWhn5qVkY6Li42OkJKUl5mbnZ6en5+enZ2cnJuZl5WUkpGPjo2Mi4qKiYmIiIeHh4aGhoWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhQ==';
    }
    
    audioRef.current.currentTime = 0;
    audioRef.current.volume = 0.3;
    audioRef.current.play().catch(() => {
      // Audio play failed, continue without sound
    });
    
    setTimeout(() => setIsBlasting(false), 500);
    onClick();
  };

  return (
    <Button
      onClick={handleClick}
      disabled={disabled || isLoading}
      className={cn(
        'relative overflow-hidden transition-all duration-300',
        'bg-gradient-to-r from-secondary via-accent to-secondary',
        'hover:from-accent hover:via-secondary hover:to-accent',
        'text-secondary-foreground font-display font-bold text-lg',
        'shadow-lg hover:shadow-xl hover:shadow-secondary/30',
        'border-2 border-secondary/50',
        isBlasting && 'animate-vuvuzela',
        className
      )}
    >
      <span className="relative z-10 flex items-center gap-2">
        {isLoading ? (
          <>
            <span className="animate-spin">⚽</span>
            Loading...
          </>
        ) : (
          <>
            📣 {children}
          </>
        )}
      </span>
    </Button>
  );
};
