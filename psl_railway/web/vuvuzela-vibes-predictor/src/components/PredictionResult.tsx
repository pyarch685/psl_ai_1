import { StadiumCard } from './StadiumCard';
import { cn } from '@/lib/utils';

interface PredictionResultProps {
  homeTeam: string;
  awayTeam: string;
  homeWin: number;
  draw: number;
  awayWin: number;
  confidence: string;
  prediction: string;
}

export const PredictionResult = ({
  homeTeam,
  awayTeam,
  homeWin,
  draw,
  awayWin,
  confidence,
  prediction,
}: PredictionResultProps) => {
  const maxProb = Math.max(homeWin, draw, awayWin);
  
  return (
    <StadiumCard title="Match Prediction" glowing>
      {/* Jumbotron style header */}
      <div className="text-center mb-6">
        <div className="inline-block bg-gradient-to-r from-primary/20 via-secondary/20 to-primary/20 px-6 py-3 rounded-lg border border-secondary/30">
          <h3 className="font-display text-3xl text-foreground">
            {homeTeam} <span className="text-secondary">vs</span> {awayTeam}
          </h3>
        </div>
      </div>

      {/* Probability bars */}
      <div className="space-y-4 mb-6">
        <ProbabilityBar 
          label={`${homeTeam} Win`}
          value={homeWin}
          isHighest={homeWin === maxProb}
          color="primary"
        />
        <ProbabilityBar 
          label="Draw"
          value={draw}
          isHighest={draw === maxProb}
          color="secondary"
        />
        <ProbabilityBar 
          label={`${awayTeam} Win`}
          value={awayWin}
          isHighest={awayWin === maxProb}
          color="accent"
        />
      </div>

      {/* Prediction announcement */}
      <div className="text-center space-y-2 py-4 bg-gradient-to-r from-transparent via-secondary/10 to-transparent rounded-lg">
        <div className="font-display text-xl text-muted-foreground uppercase">
          AI Prediction
        </div>
        <div className="font-display text-4xl text-secondary animate-pulse">
          {prediction}
        </div>
        <div className="flex items-center justify-center gap-2 text-lg">
          <span className="text-muted-foreground">Confidence:</span>
          <span className={cn(
            'font-bold px-3 py-1 rounded-full',
            confidence === 'High' && 'bg-primary/30 text-primary',
            confidence === 'Medium' && 'bg-secondary/30 text-secondary',
            confidence === 'Low' && 'bg-accent/30 text-accent',
          )}>
            {confidence}
          </span>
        </div>
      </div>

      {/* Celebration elements */}
      <div className="flex justify-center gap-4 mt-4 text-3xl animate-bounce-celebrate">
        🎉 📣 ⚽ 🇿🇦 🎊
      </div>
    </StadiumCard>
  );
};

interface ProbabilityBarProps {
  label: string;
  value: number;
  isHighest: boolean;
  color: 'primary' | 'secondary' | 'accent';
}

const ProbabilityBar = ({ label, value, isHighest, color }: ProbabilityBarProps) => {
  const colorClasses = {
    primary: 'bg-primary',
    secondary: 'bg-secondary',
    accent: 'bg-accent',
  };

  return (
    <div className="space-y-1">
      <div className="flex justify-between text-sm">
        <span className={cn(
          'font-medium',
          isHighest ? 'text-secondary' : 'text-muted-foreground'
        )}>
          {label}
        </span>
        <span className={cn(
          'font-bold',
          isHighest ? 'text-secondary' : 'text-foreground'
        )}>
          {(value * 100).toFixed(1)}%
        </span>
      </div>
      <div className="h-4 bg-muted/50 rounded-full overflow-hidden border border-primary/20">
        <div
          className={cn(
            'h-full rounded-full transition-all duration-1000',
            colorClasses[color],
            isHighest && 'animate-pulse'
          )}
          style={{ width: `${value * 100}%` }}
        />
      </div>
    </div>
  );
};
