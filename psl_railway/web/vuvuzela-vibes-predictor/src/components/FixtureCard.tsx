import { Card } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';
import { UserFeedbackModal } from './UserFeedbackModal';

interface FixtureCardProps {
  id?: number;
  homeTeam: string;
  awayTeam: string;
  date: string;
  time: string;
  venue?: string;
  prediction?: {
    homeWin: number;
    draw: number;
    awayWin: number;
    predicted: string;
  };
  isHotMatch?: boolean;
}

export const FixtureCard = ({
  id = 0,
  homeTeam,
  awayTeam,
  date,
  time,
  venue,
  prediction,
  isHotMatch,
}: FixtureCardProps) => {
  return (
    <Card 
      className={cn(
        'relative overflow-hidden p-4',
        'bg-card/60 backdrop-blur-sm',
        'border-2 border-primary/20',
        'hover:border-secondary/50 transition-all duration-300',
        'hover:shadow-lg hover:shadow-secondary/20',
        isHotMatch && 'ring-2 ring-accent/50'
      )}
    >
      {/* Ticket-style dashed border */}
      <div className="absolute left-0 top-0 bottom-0 w-2 border-r-2 border-dashed border-secondary/30" />
      <div className="absolute right-0 top-0 bottom-0 w-2 border-l-2 border-dashed border-secondary/30" />

      {/* Hot match badge */}
      {isHotMatch && (
        <Badge className="absolute top-2 right-4 bg-accent text-accent-foreground animate-pulse">
          🔥 Hot Match
        </Badge>
      )}

      <div className="pl-4 pr-4">
        {/* Teams */}
        <div className="flex items-center justify-between mb-3">
          <div className="flex-1">
            <span className="font-display text-lg text-foreground">{homeTeam}</span>
          </div>
          <div className="px-4">
            <span className="font-display text-2xl text-secondary">VS</span>
          </div>
          <div className="flex-1 text-right">
            <span className="font-display text-lg text-foreground">{awayTeam}</span>
          </div>
        </div>

        {/* Date and Time */}
        <div className="flex items-center justify-center gap-4 text-sm text-muted-foreground mb-2">
          <span>📅 {date}</span>
          <span>⏰ {time}</span>
        </div>

        {venue && (
          <div className="text-center text-sm text-muted-foreground">
            🏟️ {venue}
          </div>
        )}

        {/* Prediction preview and feedback */}
        {prediction && (
          <div className="mt-3 pt-3 border-t border-border/50">
            <div className="flex justify-between items-center text-sm">
              <div className="flex gap-2">
                <span className="text-primary">{(prediction.homeWin * 100).toFixed(0)}%</span>
                <span className="text-secondary">{(prediction.draw * 100).toFixed(0)}%</span>
                <span className="text-accent">{(prediction.awayWin * 100).toFixed(0)}%</span>
              </div>
              <Badge variant="outline" className="text-secondary border-secondary/50">
                📊 {prediction.predicted}
              </Badge>
            </div>
          </div>
        )}

        {/* User Feedback Button */}
        <div className="mt-3 flex justify-center">
          <UserFeedbackModal 
            fixtureId={id} 
            homeTeam={homeTeam} 
            awayTeam={awayTeam} 
          />
        </div>
      </div>
    </Card>
  );
};
