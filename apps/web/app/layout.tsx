import type { Metadata } from 'next';
import { AuthProvider } from '@/lib/auth';
import './globals.css';

export const metadata: Metadata = {
  title: 'Social AI — AI social media content studio',
  description: 'Generate on-brand social content with AI, organised by workspace and campaign.',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <AuthProvider>{children}</AuthProvider>
      </body>
    </html>
  );
}
