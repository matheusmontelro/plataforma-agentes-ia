import * as React from "react"

// Simplified Slot implementation to support asChild pattern without @radix-ui/react-slot
export const Slot = React.forwardRef<HTMLElement, React.HTMLAttributes<HTMLElement> & { children?: React.ReactNode }>(
    ({ children, ...props }, ref) => {
        if (React.isValidElement(children)) {
            // Basic prop merging
            const childProps = children.props as any;
            const mergedProps = {
                ...props,
                ...childProps,
                // Merge styles
                style: { ...props.style, ...childProps.style },
                // Merge classNames
                className: [props.className, childProps.className].filter(Boolean).join(" "),
            };

            // Handle ref merging (basic)
            if (ref) {
                const existingRef = (children as any).ref;
                mergedProps.ref = (node: any) => {
                    if (typeof ref === 'function') ref(node);
                    else if (ref) (ref as any).current = node;

                    if (typeof existingRef === 'function') existingRef(node);
                    else if (existingRef) (existingRef as any).current = node;
                };
            }

            return React.cloneElement(children, mergedProps);
        }
        return null;
    }
);

Slot.displayName = "Slot";
