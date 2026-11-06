import { AnimatePresence, motion } from "motion/react";
import type { ReactNode } from "react";

const EASE = [0.16, 1, 0.3, 1] as const;

/**
 * Shows one thing at a time and changes between them softly: the old one fades out quickly, the
 * new one fades in and settles a few pixels. Give it an `id` that changes when the content does.
 * People who asked for less motion get a plain change (the app's MotionConfig handles that).
 */
export function FadeSwitch({
  id,
  children,
  className,
  lift = true,
}: {
  id: string;
  children: ReactNode;
  className?: string;
  /** Settle a few pixels as it appears. Off for something that fills the window. */
  lift?: boolean;
}) {
  return (
    <AnimatePresence mode="wait" initial={false}>
      <motion.div
        key={id}
        className={className}
        initial={{ opacity: 0, y: lift ? 6 : 0 }}
        animate={{ opacity: 1, y: 0, transition: { duration: 0.2, ease: EASE } }}
        exit={{ opacity: 0, transition: { duration: 0.09, ease: "easeIn" } }}
      >
        {children}
      </motion.div>
    </AnimatePresence>
  );
}
