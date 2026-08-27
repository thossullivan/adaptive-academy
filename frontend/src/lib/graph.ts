import type { GraphEdge, GraphLink } from './types';

export const EDGE_LEGEND = [
  { kind: 'prerequisite', label: 'Prerequisite' },
  { kind: 'related', label: 'Related' }
] as const;

/** Convert the stored `concept requires prerequisite` direction for the chart. */
export function edgeToLink(edge: GraphEdge): GraphLink {
  return {
    source: edge.dst,
    target: edge.src,
    kind: edge.kind,
    weight: edge.weight
  };
}
