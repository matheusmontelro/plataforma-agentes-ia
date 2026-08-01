"use client"

import * as React from "react"
import { cn } from "../../lib/utils"

const DropdownMenuContext = React.createContext<{
    open: boolean;
    setOpen: (open: boolean) => void;
} | null>(null);

export const DropdownMenu = ({ children }: { children: React.ReactNode }) => {
    const [open, setOpen] = React.useState(false);
    const ref = React.useRef<HTMLDivElement>(null);

    React.useEffect(() => {
        const handleClick = (e: MouseEvent) => {
            if (ref.current && !ref.current.contains(e.target as Node)) {
                setOpen(false);
            }
        }
        if (open) document.addEventListener("mousedown", handleClick);
        return () => document.removeEventListener("mousedown", handleClick);
    }, [open]);

    return (
        <DropdownMenuContext.Provider value={{ open, setOpen }}>
            <div ref={ref} className="relative block w-full text-left">
                {children}
            </div>
        </DropdownMenuContext.Provider>
    )
}

export const DropdownMenuTrigger = ({ children, asChild }: { children: React.ReactNode, asChild?: boolean }) => {
    const ctx = React.useContext(DropdownMenuContext);
    if (!ctx) throw new Error("DropdownMenuTrigger must be used within DropdownMenu");

    const handleClick = (e: React.MouseEvent) => {
        ctx.setOpen(!ctx.open);
    }

    if (asChild && React.isValidElement(children)) {
        const child = children as React.ReactElement<any>;
        return React.cloneElement(child, {
            onClick: (e: any) => {
                child.props.onClick?.(e);
                handleClick(e);
            }
        });
    }

    return <button onClick={handleClick}>{children}</button>
}

export const DropdownMenuContent = ({ className, align = "center", side = "bottom", children, ...props }: React.HTMLAttributes<HTMLDivElement> & { align?: "start" | "center" | "end", side?: "top" | "bottom" | "left" | "right", sideOffset?: number }) => {
    const ctx = React.useContext(DropdownMenuContext);
    if (!ctx || !ctx.open) return null;

    return (
        <div
            className={cn(
                "absolute z-50 min-w-[8rem] overflow-hidden rounded-md border bg-popover p-1 text-popover-foreground shadow-md animate-in data-[side=bottom]:slide-in-from-top-2 data-[side=left]:slide-in-from-right-2 data-[side=right]:slide-in-from-left-2 data-[side=top]:slide-in-from-bottom-2",
                side === "bottom" && "top-full mt-2",
                side === "top" && "bottom-full mb-2",
                side === "right" && "left-full ml-2 top-0",
                align === "start" && "left-0",
                align === "end" && "right-0",
                align === "center" && "left-1/2 -translate-x-1/2",
                className
            )}
            {...props}
        >
            {children}
        </div>
    )
}

export const DropdownMenuItem = ({ className, inset, onClick, children, ...props }: React.HTMLAttributes<HTMLDivElement> & { inset?: boolean }) => {
    const ctx = React.useContext(DropdownMenuContext);
    return (
        <div
            className={cn(
                "relative flex cursor-default select-none items-center rounded-sm px-2 py-1.5 text-sm outline-none transition-colors hover:bg-accent hover:text-accent-foreground data-[disabled]:pointer-events-none data-[disabled]:opacity-50 cursor-pointer",
                inset && "pl-8",
                className
            )}
            onClick={(e) => {
                onClick?.(e);
                ctx?.setOpen(false);
            }}
            {...props}
        >
            {children}
        </div>
    )
}

export const DropdownMenuGroup = ({ className, children, ...props }: React.HTMLAttributes<HTMLDivElement>) => (
    <div className={cn("", className)} {...props}>
        {children}
    </div>
)

export const DropdownMenuLabel = ({ className, inset, ...props }: React.HTMLAttributes<HTMLDivElement> & { inset?: boolean }) => (
    <div
        className={cn("px-2 py-1.5 text-sm font-semibold", inset && "pl-8", className)}
        {...props}
    />
)

export const DropdownMenuSeparator = ({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) => (
    <div className={cn("-mx-1 my-1 h-px bg-muted", className)} {...props} />
)
