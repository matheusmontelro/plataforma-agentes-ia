import * as React from "react"
import { cn } from "../../lib/utils"

export const TooltipProvider = ({ children }: { children: React.ReactNode; delayDuration?: number }) => <>{children}</>

export const Tooltip = ({ children }: { children: React.ReactNode }) => <div className="relative group">{children}</div>

export const TooltipTrigger = React.forwardRef<HTMLElement, any>(({ asChild, children, ...props }, ref) => {
    if (asChild && React.isValidElement(children)) {
        return React.cloneElement(children as React.ReactElement<any>, { ...props, ref });
    }
    return <button ref={ref as any} {...props}>{children}</button>
})

export const TooltipContent = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement> & { side?: string, align?: string }>(
    ({ className, side = "top", align = "center", ...props }, ref) => (
        <div
            ref={ref}
            className={cn(
                "absolute z-50 overflow-hidden rounded-md border bg-popover px-3 py-1.5 text-sm text-popover-foreground shadow-md animate-in fade-in-0 zoom-in-95 data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=closed]:zoom-out-95 data-[side=bottom]:slide-in-from-top-2 data-[side=left]:slide-in-from-right-2 data-[side=right]:slide-in-from-left-2 data-[side=top]:slide-in-from-bottom-2",
                "hidden group-hover:block",
                side === "right" && "left-full top-1/2 -translate-y-1/2 ml-2",
                className
            )}
            {...props}
        />
    )
)
TooltipContent.displayName = "TooltipContent"
