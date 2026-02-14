import { useState, useEffect, useRef } from 'react';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Confetti } from '@/components/Confetti';
import { FloatingElements } from '@/components/FloatingElements';
import { HeroSection } from '@/components/HeroSection';
import { StadiumCard } from '@/components/StadiumCard';
import { TeamSelector } from '@/components/TeamSelector';
import { VuvuzelaButton } from '@/components/VuvuzelaButton';
import { PredictionResult } from '@/components/PredictionResult';
import { FixtureCard } from '@/components/FixtureCard';
import { Footer } from '@/components/Footer';
import { SoundToggle, SoundProvider } from '@/components/SoundToggle';
import { NavHeader } from '@/components/NavHeader';
import { TwitterSidebar } from '@/components/TwitterSidebar';
import { SponsorPlaceholder } from '@/components/SponsorPlaceholder';
import { SponsorBanner } from '@/components/SponsorBanner';
import { useToast } from '@/hooks/use-toast';
import { getPrediction, getFixtures, getModelStatus, getTeams, Fixture, ModelStatus, Team, isAuthenticated } from '@/lib/api';
import { Loader2 } from 'lucide-react';

const Index = () => {
  const [homeTeam, setHomeTeam] = useState('');
  const [awayTeam, setAwayTeam] = useState('');
  const [prediction, setPrediction] = useState<any>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [fixtures, setFixtures] = useState<Fixture[]>([]);
  const [fixturesLoading, setFixturesLoading] = useState(false);
  const [modelStatus, setModelStatus] = useState<ModelStatus | null>(null);
  const [statusLoading, setStatusLoading] = useState(false);
  const [teams, setTeams] = useState<Team[]>([]);
  const [teamsLoading, setTeamsLoading] = useState(true);
  const { toast } = useToast();

  // Fetch teams on mount
  useEffect(() => {
    const fetchTeams = async () => {
      setTeamsLoading(true);
      try {
        const data = await getTeams();
        setTeams(data);
      } catch (error) {
        console.log('Backend not available, using fallback teams');
        // Fallback teams if backend unavailable
        setTeams([
          { name: 'Kaizer Chiefs', value: 'kaizer_chiefs' },
          { name: 'Orlando Pirates', value: 'orlando_pirates' },
          { name: 'Mamelodi Sundowns', value: 'mamelodi_sundowns' },
          { name: 'AmaZulu FC', value: 'amazulu' },
          { name: 'Cape Town City', value: 'cape_town_city' },
          { name: 'SuperSport United', value: 'supersport_united' },
          { name: 'Golden Arrows', value: 'golden_arrows' },
          { name: 'Stellenbosch FC', value: 'stellenbosch' },
        ]);
      } finally {
        setTeamsLoading(false);
      }
    };
    fetchTeams();
  }, []);

  // Track if we've attempted to fetch fixtures
  const hasFetchedRef = useRef(false);
  
  // Fetch fixtures on mount and when authentication changes
  useEffect(() => {
    let mounted = true;
    
    const fetchFixtures = async () => {
      // Only fetch fixtures if user is authenticated
      if (!isAuthenticated()) {
        if (mounted) {
          setFixtures([]);
          setFixturesLoading(false);
          hasFetchedRef.current = false;
        }
        return;
      }

      // Don't fetch if we already have fixtures or are currently loading
      if (hasFetchedRef.current && fixtures.length > 0) {
        return;
      }

      if (mounted) {
        setFixturesLoading(true);
        hasFetchedRef.current = true;
      }
      
      try {
        const data = await getFixtures(90, 5); // Get next 5 fixtures (90 days to catch future fixtures)
        if (mounted) {
          setFixtures(data);
          console.log('Fixtures loaded successfully:', data.length);
        }
      } catch (error) {
        console.error('Failed to fetch fixtures:', error);
        const errorMessage = error instanceof Error ? error.message : 'Failed to load fixtures';
        if (mounted) {
          hasFetchedRef.current = false; // Allow retry on error
          if (errorMessage.includes('Authentication required') || errorMessage.includes('401')) {
            setFixtures([]);
            // User needs to log in - fixtures will be empty
          } else {
            // Other error - show empty state
            setFixtures([]);
          }
        }
      } finally {
        if (mounted) {
          setFixturesLoading(false);
        }
      }
    };
    
    // Initial fetch
    fetchFixtures();
    
    // Listen for storage changes (when token is added/removed in other tabs)
    const handleStorageChange = (e: StorageEvent) => {
      if (e.key === 'auth_token') {
        hasFetchedRef.current = false; // Reset to allow fetch
        fetchFixtures();
      }
    };
    
    window.addEventListener('storage', handleStorageChange);
    
    // Also check periodically (every 5 seconds) for same-tab auth changes
    // This handles the case where login happens in the same tab
    const interval = setInterval(() => {
      if (isAuthenticated() && !hasFetchedRef.current) {
        // Only fetch if we haven't fetched yet
        fetchFixtures();
      }
    }, 5000);
    
    return () => {
      mounted = false;
      window.removeEventListener('storage', handleStorageChange);
      clearInterval(interval);
    };
  }, []); // Empty dependency array - only run on mount

  // Fetch model status
  const fetchModelStatus = async () => {
    setStatusLoading(true);
    try {
      const data = await getModelStatus();
      setModelStatus(data);
    } catch (error) {
      setModelStatus({ status: 'offline', accuracy: undefined, last_trained: undefined });
    } finally {
      setStatusLoading(false);
    }
  };

  const handlePredict = async () => {
    if (!homeTeam || !awayTeam) {
      toast({ title: 'Eish!', description: 'Please select both teams', variant: 'destructive' });
      return;
    }
    if (homeTeam === awayTeam) {
      toast({ title: 'Haibo!', description: 'Teams cannot be the same', variant: 'destructive' });
      return;
    }

    setIsLoading(true);
    try {
      // Get team names from teams list
      const homeTeamName = teams.find(t => t.value === homeTeam)?.name || homeTeam;
      const awayTeamName = teams.find(t => t.value === awayTeam)?.name || awayTeam;
      
      const result = await getPrediction(homeTeamName, awayTeamName);
      setPrediction({
        homeTeam: result.home_team,
        awayTeam: result.away_team,
        homeWin: result.home_win,
        draw: result.draw,
        awayWin: result.away_win,
        prediction: result.prediction,
        confidence: result.confidence,
      });
    } catch (error) {
      toast({ 
        title: 'Connection Error', 
        description: 'Could not connect to backend. Make sure FastAPI is running on localhost:8000', 
        variant: 'destructive' 
      });
      // Fallback mock prediction
      const homeWin = Math.random() * 0.5 + 0.2;
      const draw = Math.random() * 0.3;
      const awayWin = 1 - homeWin - draw;
      const max = Math.max(homeWin, draw, awayWin);
      setPrediction({
        homeTeam: teams.find(t => t.value === homeTeam)?.name || homeTeam,
        awayTeam: teams.find(t => t.value === awayTeam)?.name || awayTeam,
        homeWin, draw, awayWin,
        prediction: max === homeWin ? 'Home Win' : max === draw ? 'Draw' : 'Away Win',
        confidence: max > 0.5 ? 'High' : max > 0.4 ? 'Medium' : 'Low',
      });
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <SoundProvider>
      <div className="min-h-screen stadium-gradient relative overflow-hidden">
        <NavHeader />
        <Confetti />
        <FloatingElements />
        <SoundToggle />
        
        <HeroSection />

        <div className="container mx-auto px-4 py-8 relative z-10">
          <div className="flex justify-center gap-6 items-stretch">
            <SponsorPlaceholder side="left" />

            <main className="w-full max-w-4xl flex flex-col">
          <Tabs defaultValue="predict" className="w-full">
            <TabsList className="w-full grid grid-cols-3 bg-card/50 backdrop-blur-sm border-2 border-primary/30 p-1 mb-8">
              <TabsTrigger value="predict" className="font-display text-lg data-[state=active]:bg-primary data-[state=active]:text-primary-foreground">
                📊 Predict
              </TabsTrigger>
              <TabsTrigger value="fixtures" className="font-display text-lg data-[state=active]:bg-secondary data-[state=active]:text-secondary-foreground">
                📅 Fixtures
              </TabsTrigger>
              <TabsTrigger 
                value="status" 
                className="font-display text-lg data-[state=active]:bg-accent data-[state=active]:text-accent-foreground"
                onClick={fetchModelStatus}
              >
                ⚙️ Status
              </TabsTrigger>
            </TabsList>

            <TabsContent value="predict" className="space-y-6">
              <StadiumCard title="Single Match Prediction">
                {teamsLoading ? (
                  <div className="flex justify-center py-8">
                    <Loader2 className="h-8 w-8 animate-spin text-secondary" />
                  </div>
                ) : (
                  <>
                    <div className="grid md:grid-cols-2 gap-6 mb-6">
                      <TeamSelector teams={teams} value={homeTeam} onChange={setHomeTeam} label="Home Team" placeholder="Select home team" />
                      <TeamSelector teams={teams} value={awayTeam} onChange={setAwayTeam} label="Away Team" placeholder="Select away team" />
                    </div>
                    <div className="flex justify-center">
                      <VuvuzelaButton onClick={handlePredict} isLoading={isLoading} disabled={teamsLoading || teams.length === 0} className="px-12 py-6 text-xl">
                        Get Prediction
                      </VuvuzelaButton>
                    </div>
                  </>
                )}
              </StadiumCard>

              {prediction && <PredictionResult {...prediction} />}
            </TabsContent>

            <TabsContent value="fixtures">
              <StadiumCard title="Upcoming Fixtures">
                {fixturesLoading ? (
                  <div className="flex justify-center py-8">
                    <Loader2 className="h-8 w-8 animate-spin text-secondary" />
                  </div>
                ) : (
                  <div className="space-y-4">
                    {fixtures.map((fixture) => (
                      <FixtureCard 
                        key={fixture.id} 
                        id={fixture.id}
                        homeTeam={fixture.home_team} 
                        awayTeam={fixture.away_team}
                        date={fixture.date}
                        time={fixture.time}
                        venue={fixture.venue}
                        isHotMatch={fixture.is_hot_match}
                        prediction={fixture.prediction ? {
                          homeWin: fixture.prediction.home_win,
                          draw: fixture.prediction.draw,
                          awayWin: fixture.prediction.away_win,
                          predicted: fixture.prediction.predicted,
                        } : undefined}
                      />
                    ))}
                  </div>
                )}
              </StadiumCard>
            </TabsContent>

            <TabsContent value="status">
              <StadiumCard title="Model Status">
                {statusLoading ? (
                  <div className="flex justify-center py-8">
                    <Loader2 className="h-8 w-8 animate-spin text-secondary" />
                  </div>
                ) : (
                  <div className="text-center py-8">
                    <div className="text-6xl mb-4">
                      {modelStatus?.status === 'ready' ? '✅' : modelStatus?.status === 'offline' ? '❌' : '🤖'}
                    </div>
                    <p className="text-xl text-secondary font-display capitalize">
                      {modelStatus?.status || 'Click to check status'}
                    </p>
                    {modelStatus?.accuracy && (
                      <p className="text-muted-foreground mt-2">
                        Accuracy: {(modelStatus.accuracy * 100).toFixed(1)}%
                      </p>
                    )}
                    {modelStatus?.last_trained && (
                      <p className="text-muted-foreground mt-1">
                        Last trained: {modelStatus.last_trained}
                      </p>
                    )}
                    {modelStatus?.total_predictions && (
                      <p className="text-muted-foreground mt-1">
                        Total predictions: {modelStatus.total_predictions.toLocaleString()}
                      </p>
                    )}
                    <p className="text-sm text-muted-foreground/70 mt-4">
                      Backend: localhost:8000
                    </p>
                  </div>
                )}
              </StadiumCard>
            </TabsContent>
          </Tabs>

              <div className="mt-8">
                <TwitterSidebar twitterHandle="OfficialPSL" />
              </div>
              <SponsorBanner />
            </main>

            <SponsorPlaceholder side="right" />
          </div>
        </div>

        <Footer />
      </div>
    </SoundProvider>
  );
};

export default Index;