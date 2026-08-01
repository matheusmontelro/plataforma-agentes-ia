// Simplified cn utility since clsx/tailwind-merge are not available
export function cn(...inputs: (string | undefined | null | false)[]) {
    return inputs.filter(Boolean).join(" ")
}
