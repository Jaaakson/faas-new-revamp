"use client";

import * as React from "react";
import * as SliderPrimitive from "@radix-ui/react-slider";

import { cn } from "@/lib/utils";

/**
 * Radix gives the slider full keyboard support (arrows, Home/End, PageUp/Down)
 * and the aria-valuenow/min/max wiring. A div-and-drag implementation is
 * unusable without a mouse, which rules it out for the pricing calculator.
 */
const Slider = React.forwardRef<
  React.ComponentRef<typeof SliderPrimitive.Root>,
  React.ComponentPropsWithoutRef<typeof SliderPrimitive.Root>
>(
  (
    {
      className,
      // The Thumb is the element carrying role="slider", and Radix does NOT
      // forward these from Root — set on Root they are silently dropped, and
      // the control announces as an unnamed slider. They must land on the Thumb.
      "aria-label": ariaLabel,
      "aria-labelledby": ariaLabelledby,
      "aria-valuetext": ariaValuetext,
      ...props
    },
    ref,
  ) => (
    <SliderPrimitive.Root
      ref={ref}
      className={cn("relative flex w-full touch-none items-center select-none", className)}
      {...props}
    >
      <SliderPrimitive.Track className="bg-secondary relative h-1.5 w-full grow overflow-hidden rounded-full">
        <SliderPrimitive.Range className="bg-primary absolute h-full" />
      </SliderPrimitive.Track>
      <SliderPrimitive.Thumb
        aria-label={ariaLabel}
        aria-labelledby={ariaLabelledby}
        // aria-valuetext overrides how aria-valuenow is announced. Essential
        // when the underlying value is not the number the user is choosing —
        // a logarithmic scale announces "4" for 10,000 without it.
        aria-valuetext={ariaValuetext}
        className="border-primary bg-background ring-offset-background focus-visible:ring-ring block size-4 rounded-full border-2 shadow transition-colors focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:outline-none disabled:pointer-events-none disabled:opacity-50"
      />
    </SliderPrimitive.Root>
  ),
);
Slider.displayName = "Slider";

export { Slider };
