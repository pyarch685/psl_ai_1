import { useEffect, useState } from 'react';

interface ConfettiPiece {
  id: number;
  left: number;
  delay: number;
  duration: number;
  color: string;
  size: number;
}

const COLORS = [
  'hsl(45 100% 50%)', // Gold
  'hsl(142 71% 45%)', // Green
  'hsl(25 95% 53%)', // Orange
  'hsl(0 85% 47%)', // Red
  'hsl(210 100% 35%)', // Blue
  'hsl(0 0% 100%)', // White
];

export const Confetti = () => {
  const [pieces, setPieces] = useState<ConfettiPiece[]>([]);

  useEffect(() => {
    const confettiPieces: ConfettiPiece[] = Array.from({ length: 50 }, (_, i) => ({
      id: i,
      left: Math.random() * 100,
      delay: Math.random() * 5,
      duration: 3 + Math.random() * 4,
      color: COLORS[Math.floor(Math.random() * COLORS.length)],
      size: 6 + Math.random() * 8,
    }));
    setPieces(confettiPieces);
  }, []);

  return (
    <div className="fixed inset-0 pointer-events-none overflow-hidden z-0">
      {pieces.map((piece) => (
        <div
          key={piece.id}
          className="absolute animate-confetti"
          style={{
            left: `${piece.left}%`,
            animationDelay: `${piece.delay}s`,
            animationDuration: `${piece.duration}s`,
            width: piece.size,
            height: piece.size,
            backgroundColor: piece.color,
            transform: `rotate(${Math.random() * 360}deg)`,
          }}
        />
      ))}
    </div>
  );
};
