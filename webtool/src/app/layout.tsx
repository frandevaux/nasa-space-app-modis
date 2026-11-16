import type { Metadata } from 'next';
import { Inter, Inter_Tight } from 'next/font/google';
import './globals.css';

const inter = Inter({ subsets: ['latin'], weight: ['300', '400', '500', '600', '700'], variable: '--font-inter' });
const interTight = Inter_Tight({ subsets: ['latin'], weight: ['400', '500', '600', '700'], variable: '--font-inter-tight' });

export const metadata: Metadata = {
  title: 'Mente Fría',
  description: 'Historial armonizado de hotspots MODIS + VIIRS, fires y firewaves, pronóstico y bitácora de campo. NASA Space Apps 2026 · Equipo Firewall.',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="es" className={`${inter.variable} ${interTight.variable}`}>
      <body>{children}</body>
    </html>
  );
}
