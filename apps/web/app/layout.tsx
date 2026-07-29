import type { Metadata, Viewport } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'Social AI — AI social media content platform',
  description:
    'Generate on-brand social media content with AI. Workspaces, brand voice, campaigns and conversation history.',
  robots: { index: true, follow: true },
};

export const viewport: Viewport = {
  themeColor: '#020617',
  width: 'device-width',
  initialScale: 1,
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
