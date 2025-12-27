import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { cn } from '@/lib/utils';

interface Team {
  name: string;
  value: string;
}

interface TeamSelectorProps {
  teams: Team[];
  value: string;
  onChange: (value: string) => void;
  label: string;
  placeholder?: string;
}

const getTeamColors = (teamName: string): string => {
  const lowerName = teamName.toLowerCase();
  if (lowerName.includes('chiefs') || lowerName.includes('kaizer')) {
    return 'border-l-4 border-l-chiefs-gold';
  }
  if (lowerName.includes('pirates') || lowerName.includes('orlando')) {
    return 'border-l-4 border-l-pirates-white';
  }
  if (lowerName.includes('sundowns') || lowerName.includes('mamelodi')) {
    return 'border-l-4 border-l-sundowns-yellow';
  }
  if (lowerName.includes('amazulu')) {
    return 'border-l-4 border-l-sa-green';
  }
  if (lowerName.includes('cape town')) {
    return 'border-l-4 border-l-sa-blue';
  }
  return 'border-l-4 border-l-primary';
};

export const TeamSelector = ({ 
  teams, 
  value, 
  onChange, 
  label,
  placeholder = "Select a team" 
}: TeamSelectorProps) => {
  const selectedTeam = teams.find(t => t.value === value);
  
  return (
    <div className="space-y-2">
      <label className="font-display text-lg text-secondary uppercase tracking-wider">
        {label}
      </label>
      <Select value={value} onValueChange={onChange}>
        <SelectTrigger 
          className={cn(
            'w-full h-14 text-lg font-medium',
            'bg-muted/50 border-2 border-primary/30',
            'hover:border-secondary/50 transition-colors',
            'focus:ring-2 focus:ring-secondary/50',
            selectedTeam && getTeamColors(selectedTeam.name)
          )}
        >
          <SelectValue placeholder={placeholder} />
        </SelectTrigger>
        <SelectContent className="bg-card border-primary/30">
          {teams.map((team) => (
            <SelectItem 
              key={team.value} 
              value={team.value}
              className={cn(
                'text-lg py-3 cursor-pointer',
                'hover:bg-primary/20',
                getTeamColors(team.name)
              )}
            >
              <span className="flex items-center gap-2">
                ⚽ {team.name}
              </span>
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
};
