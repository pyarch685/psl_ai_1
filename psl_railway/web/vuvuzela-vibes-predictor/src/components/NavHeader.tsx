import { useState } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { User, LogIn, Loader2, BarChart3 } from 'lucide-react';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog';
import { registerUser, loginUser, logoutUser, isAuthenticated } from '@/lib/api';
import { useToast } from '@/hooks/use-toast';

export const NavHeader = () => {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [isLoginOpen, setIsLoginOpen] = useState(false);
  const [isRegisterOpen, setIsRegisterOpen] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [loginError, setLoginError] = useState('');
  const [registerError, setRegisterError] = useState('');
  const [loggedIn, setLoggedIn] = useState(isAuthenticated());
  const { toast } = useToast();
  const navigate = useNavigate();
  const location = useLocation();

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoginError('');
    setIsLoading(true);
    
    try {
      const result = await loginUser(email, password);
      setLoggedIn(true);
      toast({
        title: 'Welcome back!',
        description: result.message,
      });
      setIsLoginOpen(false);
      setEmail('');
      setPassword('');
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : 'Login failed';
      setLoginError(errorMessage);
      toast({
        title: 'Login failed',
        description: errorMessage,
        variant: 'destructive',
      });
    } finally {
      setIsLoading(false);
    }
  };

  const handleRegister = async (e: React.FormEvent) => {
    e.preventDefault();
    setRegisterError('');
    setIsLoading(true);
    
    try {
      const result = await registerUser(email, password);
      toast({
        title: 'Account created!',
        description: result.message,
      });
      setIsRegisterOpen(false);
      setEmail('');
      setPassword('');
      // Switch to login dialog
      setIsLoginOpen(true);
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : 'Registration failed';
      setRegisterError(errorMessage);
      toast({
        title: 'Registration failed',
        description: errorMessage,
        variant: 'destructive',
      });
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <header className="sticky top-0 z-50 w-full border-b border-border/40 bg-background/80 backdrop-blur-md">
      <div className="container mx-auto flex h-14 items-center justify-between px-4">
        {/* Logo */}
        <div className="flex items-center gap-2">
          <span className="text-2xl">⚽</span>
          <span className="font-display text-xl font-bold text-primary">PSL Predictor</span>
        </div>

        {/* Nav Links */}
        <div className="flex items-center gap-1">
          <Button
            variant={location.pathname === '/' ? 'secondary' : 'ghost'}
            size="sm"
            onClick={() => navigate('/')}
            className="gap-1"
          >
            ⚽ <span className="hidden sm:inline">Predictor</span>
          </Button>
          <Button
            variant={location.pathname === '/benchmark' ? 'secondary' : 'ghost'}
            size="sm"
            onClick={() => navigate('/benchmark')}
            className="gap-1"
          >
            <BarChart3 className="h-4 w-4" />
            <span className="hidden sm:inline">Benchmark</span>
          </Button>
        </div>

        {/* Auth Buttons */}
        <div className="flex items-center gap-2">
          {loggedIn ? (
            <Button 
              variant="ghost" 
              size="sm" 
              className="gap-2"
              onClick={() => {
                logoutUser();
                setLoggedIn(false);
                toast({
                  title: 'Logged out',
                  description: 'You have been successfully logged out.',
                });
              }}
            >
              <LogIn className="h-4 w-4" />
              <span className="hidden sm:inline">Logout</span>
            </Button>
          ) : (
            <>
              {/* Login Dialog */}
              <Dialog open={isLoginOpen} onOpenChange={setIsLoginOpen}>
            <DialogTrigger asChild>
              <Button variant="ghost" size="sm" className="gap-2">
                <LogIn className="h-4 w-4" />
                <span className="hidden sm:inline">Login</span>
              </Button>
            </DialogTrigger>
            <DialogContent className="sm:max-w-md">
              <DialogHeader>
                <DialogTitle className="flex items-center gap-2 font-display">
                  <LogIn className="h-5 w-5 text-primary" />
                  Login to PSL Predictor
                </DialogTitle>
              </DialogHeader>
              <form onSubmit={handleLogin} className="space-y-4 mt-4">
                <div className="space-y-2">
                  <label htmlFor="login-email" className="text-sm font-medium">
                    Email
                  </label>
                  <Input
                    id="login-email"
                    type="email"
                    placeholder="your@email.com"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    required
                  />
                </div>
                <div className="space-y-2">
                  <label htmlFor="login-password" className="text-sm font-medium">
                    Password
                  </label>
                  <Input
                    id="login-password"
                    type="password"
                    placeholder="••••••••"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    required
                  />
                </div>
                {loginError && (
                  <p className="text-sm text-destructive">{loginError}</p>
                )}
                <Button type="submit" className="w-full" disabled={isLoading}>
                  {isLoading ? (
                    <>
                      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                      Logging in...
                    </>
                  ) : (
                    'Login'
                  )}
                </Button>
                <p className="text-center text-sm text-muted-foreground">
                  Don't have an account?{' '}
                  <button
                    type="button"
                    className="text-primary hover:underline"
                    onClick={() => {
                      setIsLoginOpen(false);
                      setIsRegisterOpen(true);
                    }}
                  >
                    Register
                  </button>
                </p>
              </form>
            </DialogContent>
          </Dialog>

          {/* Register Dialog */}
          <Dialog open={isRegisterOpen} onOpenChange={setIsRegisterOpen}>
            <DialogTrigger asChild>
              <Button variant="outline" size="sm" className="gap-2 border-primary/50 hover:bg-primary/10">
                <User className="h-4 w-4" />
                <span className="hidden sm:inline">Register</span>
              </Button>
            </DialogTrigger>
            <DialogContent className="sm:max-w-md">
              <DialogHeader>
                <DialogTitle className="flex items-center gap-2 font-display">
                  <User className="h-5 w-5 text-primary" />
                  Create an Account
                </DialogTitle>
              </DialogHeader>
              <form onSubmit={handleRegister} className="space-y-4 mt-4">
                <div className="space-y-2">
                  <label htmlFor="register-email" className="text-sm font-medium">
                    Email
                  </label>
                  <Input
                    id="register-email"
                    type="email"
                    placeholder="your@email.com"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    required
                  />
                </div>
                <div className="space-y-2">
                  <label htmlFor="register-password" className="text-sm font-medium">
                    Password
                  </label>
                  <Input
                    id="register-password"
                    type="password"
                    placeholder="••••••••"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    required
                  />
                </div>
                {registerError && (
                  <p className="text-sm text-destructive">{registerError}</p>
                )}
                <div className="text-xs text-muted-foreground mb-2">
                  Password must: be 8+ characters, include uppercase, lowercase, digit, and special character
                </div>
                <Button type="submit" className="w-full" disabled={isLoading}>
                  {isLoading ? (
                    <>
                      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                      Creating account...
                    </>
                  ) : (
                    'Create Account'
                  )}
                </Button>
                <p className="text-center text-sm text-muted-foreground">
                  Already have an account?{' '}
                  <button
                    type="button"
                    className="text-primary hover:underline"
                    onClick={() => {
                      setIsRegisterOpen(false);
                      setIsLoginOpen(true);
                    }}
                  >
                    Login
                  </button>
                </p>
              </form>
            </DialogContent>
          </Dialog>
            </>
          )}
        </div>
      </div>
    </header>
  );
};
