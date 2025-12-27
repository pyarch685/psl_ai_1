import { useEffect, useState } from 'react';
import vuvuzelaMascot from '@/assets/vuvuzela-mascot.png';

interface FloatingElement {
  id: number;
  type: 'ball' | 'flag' | 'mascot';
  left: number;
  delay: number;
  size: number;
}

export const FloatingElements = () => {
  const [elements, setElements] = useState<FloatingElement[]>([]);

  useEffect(() => {
    const floatingElements: FloatingElement[] = [
      // Soccer balls
      ...Array.from({ length: 5 }, (_, i) => ({
        id: i,
        type: 'ball' as const,
        left: 5 + i * 20,
        delay: i * 0.5,
        size: 30 + Math.random() * 20,
      })),
      // SA Flags
      ...Array.from({ length: 3 }, (_, i) => ({
        id: i + 5,
        type: 'flag' as const,
        left: 15 + i * 30,
        delay: i * 0.8,
        size: 40 + Math.random() * 20,
      })),
    ];
    setElements(floatingElements);
  }, []);

  const renderElement = (element: FloatingElement) => {
    switch (element.type) {
      case 'ball':
        return (
          <span 
            className="text-4xl drop-shadow-lg"
            style={{ fontSize: element.size }}
          >
            ⚽
          </span>
        );
      case 'flag':
        return (
          <span 
            className="text-4xl drop-shadow-lg animate-flag-wave"
            style={{ fontSize: element.size }}
          >
            🇿🇦
          </span>
        );
      case 'mascot':
        return (
          <img 
            src={vuvuzelaMascot} 
            alt="Vuvuzela Mascot" 
            className="drop-shadow-lg"
            style={{ width: element.size, height: element.size }}
          />
        );
      default:
        return null;
    }
  };

  return (
    <div className="fixed inset-0 pointer-events-none overflow-hidden z-0">
      {elements.map((element) => (
        <div
          key={element.id}
          className="absolute animate-float opacity-60"
          style={{
            left: `${element.left}%`,
            top: `${20 + Math.random() * 60}%`,
            animationDelay: `${element.delay}s`,
            animationDuration: `${3 + Math.random() * 2}s`,
          }}
        >
          {renderElement(element)}
        </div>
      ))}
    </div>
  );
};
