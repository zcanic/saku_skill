import React from 'react';
import { createRoot } from 'react-dom/client';
import { Theme } from '@radix-ui/themes';
import { MotionConfig } from 'motion/react';
import '@radix-ui/themes/styles.css';
import 'katex/dist/katex.min.css';
import './styles.css';
import App from './App';

// Follow the reader's system theme; the stylesheet tokens switch with it.
function Root() {
  const query=window.matchMedia('(prefers-color-scheme: dark)');
  const [dark,setDark]=React.useState(query.matches);
  React.useEffect(()=>{const on=(e:MediaQueryListEvent)=>setDark(e.matches);query.addEventListener('change',on);return()=>query.removeEventListener('change',on);},[query]);
  return <Theme appearance={dark?'dark':'light'} accentColor="teal" grayColor="sand" radius="medium" scaling="100%">
    <MotionConfig reducedMotion="user"><App/></MotionConfig>
  </Theme>;
}

createRoot(document.getElementById('root')!).render(<React.StrictMode><Root/></React.StrictMode>);
