import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import { Label } from '@/components/ui/label';
import { ThumbsUp, Loader2 } from 'lucide-react';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog';
import { submitUserFeedback, UserFeedback } from '@/lib/api';
import { useToast } from '@/hooks/use-toast';

interface UserFeedbackModalProps {
  fixtureId: number;
  homeTeam: string;
  awayTeam: string;
}

export const UserFeedbackModal = ({ fixtureId, homeTeam, awayTeam }: UserFeedbackModalProps) => {
  const [isOpen, setIsOpen] = useState(false);
  const [selectedPrediction, setSelectedPrediction] = useState<'home_win' | 'draw' | 'away_win' | ''>('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const { toast } = useToast();

  const handleSubmit = async () => {
    if (!selectedPrediction) {
      toast({
        title: 'Eish!',
        description: 'Please select your prediction',
        variant: 'destructive',
      });
      return;
    }

    setIsSubmitting(true);
    try {
      const feedback: UserFeedback = {
        fixture_id: fixtureId,
        home_team: homeTeam,
        away_team: awayTeam,
        user_prediction: selectedPrediction,
      };

      await submitUserFeedback(feedback);
      
      toast({
        title: 'Sharp!',
        description: 'Your prediction has been recorded',
      });
      setIsOpen(false);
      setSelectedPrediction('');
    } catch (error) {
      toast({
        title: 'Haibo!',
        description: 'Failed to submit prediction. Is the backend running?',
        variant: 'destructive',
      });
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <Dialog open={isOpen} onOpenChange={setIsOpen}>
      <DialogTrigger asChild>
        <Button variant="outline" size="sm" className="gap-2 border-secondary/50 hover:bg-secondary/10">
          <ThumbsUp className="h-4 w-4" />
          <span className="hidden sm:inline">Your Prediction</span>
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="font-display text-center">
            What's Your Prediction?
          </DialogTitle>
        </DialogHeader>
        <div className="space-y-6 mt-4">
          <div className="text-center">
            <span className="text-primary font-display text-lg">{homeTeam}</span>
            <span className="text-muted-foreground mx-3">vs</span>
            <span className="text-accent font-display text-lg">{awayTeam}</span>
          </div>

          <RadioGroup 
            value={selectedPrediction} 
            onValueChange={(value) => setSelectedPrediction(value as 'home_win' | 'draw' | 'away_win')}
            className="flex flex-col gap-3"
          >
            <div className="flex items-center space-x-3 p-3 rounded-lg border border-primary/30 hover:bg-primary/10 transition-colors">
              <RadioGroupItem value="home_win" id="home_win" />
              <Label htmlFor="home_win" className="flex-1 cursor-pointer font-medium">
                {homeTeam} Win
              </Label>
            </div>
            <div className="flex items-center space-x-3 p-3 rounded-lg border border-secondary/30 hover:bg-secondary/10 transition-colors">
              <RadioGroupItem value="draw" id="draw" />
              <Label htmlFor="draw" className="flex-1 cursor-pointer font-medium">
                Draw
              </Label>
            </div>
            <div className="flex items-center space-x-3 p-3 rounded-lg border border-accent/30 hover:bg-accent/10 transition-colors">
              <RadioGroupItem value="away_win" id="away_win" />
              <Label htmlFor="away_win" className="flex-1 cursor-pointer font-medium">
                {awayTeam} Win
              </Label>
            </div>
          </RadioGroup>

          <Button 
            onClick={handleSubmit} 
            className="w-full" 
            disabled={!selectedPrediction || isSubmitting}
          >
            {isSubmitting ? (
              <>
                <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                Submitting...
              </>
            ) : (
              'Submit Prediction'
            )}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
};
