import * as React from "react"
import { cn } from "../../lib/utils"

// Simplified Sheet (Mobile Drawer) using fixed positioning and state

export const Sheet = ({ children, open, onOpenChange }: { children: React.ReactNode, open?: boolean, onOpenChange?: (open: boolean) => void }) => {
    if (!open) return null;
    return (
        <div className="fixed inset-0 z-50 bg-black/80" onClick={() => onOpenChange?.(false)}>
            <div onClick={(e) => e.stopPropagation()}>
                {children}
            </div>
        </div>
    )
}

export const SheetContent = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement> & { side?: string }>(
    ({ className, side = "left", children, ...props }, ref) => (
        <div
            ref={ref}
            className={cn(
                "fixed z-50 gap-4 bg-background p-6 shadow-lg transition ease-in-out data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:duration-300 data-[state=open]:duration-500",
                "inset-y-0 left-0 h-full w-3/4 border-r data-[state=closed]:slide-out-to-left data-[state=open]:slide-in-from-left sm:max-w-sm",
                className
            )}
            {...props}
        >
            {children}
        </div>
    )
)
SheetContent.displayName = "SheetContent"
