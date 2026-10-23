import React from 'react';
import { createRoot } from 'react-dom/client';
import { Theme } from '@radix-ui/themes';
import { MotionConfig } from 'motion/react';
import '@radix-ui/themes/styles.css';
import 'katex/dist/katex.min.css';
import './styles.css';
import App from './App';

createRoot(document.getElementById('root')!).render(
  <React.StrictMode><Theme appearance="light" accentColor="teal" grayColor="sand" radius="small" scaling="100%">
    <MotionConfig reducedMotion="user"><App/></MotionConfig>
  </Theme></React.StrictMode>
);
