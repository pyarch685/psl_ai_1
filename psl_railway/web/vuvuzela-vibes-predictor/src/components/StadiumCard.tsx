import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { cn } from '@/lib/utils';

interface StadiumCardProps {
  title: string;
  children: React.ReactNode;
  className?: string;
  glowing?: boolean;
}

export const StadiumCard = ({ title, children, className, glowing }: StadiumCardProps) => {
  return (
    <Card 
      className={cn(
        'relative overflow-hidden',
        'bg-card/80 backdrop-blur-sm',
        'border-2 border-primary/30',
        'shadow-xl',
        glowing && 'animate-pulse-glow',
        className
      )}
    >
      {/* Stadium lights effect */}
      <div className="absolute inset-0 floodlight-overlay pointer-events-none" />
      
      {/* Top border accent */}
      <div className="absolute top-0 left-0 right-0 h-1 sa-flag-gradient" />
      
      <CardHeader className="relative">
        <CardTitle className="font-display text-2xl text-secondary flex items-center gap-2">
          <span className="text-2xl">⚽</span>
          {title}
        </CardTitle>
      </CardHeader>
      
      <CardContent className="relative">
        {children}
      </CardContent>
    </Card>
  );
};
