export interface LeadEntrySortable {
  date?: Date | string | null;
  id: number;
}

const getEntryTimestamp = (date: LeadEntrySortable['date']): number | null => {
  if (!date) return null;

  const timestamp = date instanceof Date ? date.getTime() : Date.parse(date);
  return Number.isFinite(timestamp) ? timestamp : null;
};

export const compareLeadsByEntryRecency = (
  first: LeadEntrySortable,
  second: LeadEntrySortable,
): number => {
  const firstTimestamp = getEntryTimestamp(first.date);
  const secondTimestamp = getEntryTimestamp(second.date);

  if (firstTimestamp === null && secondTimestamp === null) return second.id - first.id;
  if (firstTimestamp === null) return 1;
  if (secondTimestamp === null) return -1;
  if (firstTimestamp === secondTimestamp) return second.id - first.id;

  return secondTimestamp - firstTimestamp;
};

export const sortLeadsByEntryRecency = <LeadType extends LeadEntrySortable>(
  leads: LeadType[],
): LeadType[] => [...leads].sort(compareLeadsByEntryRecency);
