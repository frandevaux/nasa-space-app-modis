'use client';
/*
 * Dashboard menu: a square button that, when pressed, expands from its corner into the menu itself.
 * The menu has a close (×) button and also closes with Escape. The button shows its name on hover.
 */
import { useEffect, useRef, type ReactNode } from 'react';
import { Icon } from './icons';

export type Corner = 'top-left' | 'bottom-left' | 'top-right';

interface Props {
  label: string;
  icon: ReactNode;
  open: boolean;
  corner: Corner;
  onOpen: () => void;
  onClose: () => void;
  className?: string;
  children: ReactNode;
}

export default function DashMenu({ label, icon, open, corner, onOpen, onClose, className = '', children }: Props) {
  const closeRef = useRef<HTMLButtonElement>(null);
  const wasOpen = useRef(open);
  const btnRef = useRef<HTMLButtonElement>(null);

  // Keep keyboard focus in place: on the × after opening, back on the button after closing.
  useEffect(() => {
    if (open && !wasOpen.current) { closeRef.current?.focus({ preventScroll: true }); }
    if (!open && wasOpen.current && document.activeElement === document.body) { btnRef.current?.focus({ preventScroll: true }); }
    wasOpen.current = open;
  }, [open]);

  if (!open) {
    return (
      <button ref={btnRef} type="button" className={`dash-btn dash-btn--${corner}`} aria-label={label} aria-expanded={false} data-tip={label} onClick={onOpen}>
        {icon}
      </button>
    );
  }
  return (
    <section
      className={`panel dash-card dash-menu dash-menu--${corner} ${className}`}
      aria-label={label}
      onKeyDown={(e) => { if (e.key === 'Escape') { e.stopPropagation(); onClose(); } }}
    >
      <div className="dash-menu__head">
        <span className="dash-menu__icon" aria-hidden="true">{icon}</span>
        <span className="dash-menu__title">{label}</span>
        <button ref={closeRef} type="button" className="dash-menu__close" aria-label={`Cerrar ${label.toLowerCase()}`} onClick={onClose}><Icon.close /></button>
      </div>
      <div className="dash-menu__body">{children}</div>
    </section>
  );
}
