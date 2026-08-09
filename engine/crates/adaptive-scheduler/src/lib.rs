//! Adaptive Range Queue and Work Stealing scheduling algorithm for Barq downloads.

use serde::{Deserialize, Serialize};

pub const MIN_STEAL_THRESHOLD: u64 = 512 * 1024; // 512 KiB minimum chunk size to steal

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct RangeSegment {
    pub id: usize,
    pub start: u64,
    pub end: u64,
    pub current: u64,
    pub completed: bool,
}

impl RangeSegment {
    pub fn remaining_bytes(&self) -> u64 {
        if self.completed || self.current > self.end {
            0
        } else {
            self.end - self.current + 1
        }
    }
}

pub struct DynamicRangeQueue {
    pub segments: Vec<RangeSegment>,
}

impl DynamicRangeQueue {
    pub fn new(total_bytes: u64, parts: usize) -> Self {
        if total_bytes == 0 || parts == 0 {
            return Self {
                segments: Vec::new(),
            };
        }

        let segment_count = if total_bytes < parts as u64 {
            total_bytes as usize
        } else {
            parts
        };
        let chunk_size = total_bytes / segment_count as u64;
        let extra_bytes = total_bytes % segment_count as u64;
        let mut segments = Vec::with_capacity(segment_count);
        let mut start = 0;

        for i in 0..segment_count {
            let size = chunk_size + u64::from((i as u64) < extra_bytes);
            let end = start + size - 1;
            segments.push(RangeSegment {
                id: i,
                start,
                end,
                current: start,
                completed: false,
            });
            start = end + 1;
        }

        Self { segments }
    }

    /// Try to steal work from the slowest active segment with the largest remaining workload.
    pub fn try_steal_work(&mut self) -> Option<RangeSegment> {
        let mut max_remaining = 0;
        let mut target_idx = None;

        for (idx, seg) in self.segments.iter().enumerate() {
            let rem = seg.remaining_bytes();
            if rem > MIN_STEAL_THRESHOLD && rem > max_remaining {
                max_remaining = rem;
                target_idx = Some(idx);
            }
        }

        if let Some(idx) = target_idx {
            let seg = &mut self.segments[idx];
            let half = seg.remaining_bytes() / 2;
            let new_end = seg.current + half;
            let stolen_start = new_end + 1;
            let stolen_end = seg.end;

            seg.end = new_end;

            let new_id = self.segments.len();
            let stolen_segment = RangeSegment {
                id: new_id,
                start: stolen_start,
                end: stolen_end,
                current: stolen_start,
                completed: false,
            };

            self.segments.push(stolen_segment.clone());
            Some(stolen_segment)
        } else {
            None
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_queue_partitioning() {
        let queue = DynamicRangeQueue::new(1000, 4);
        assert_eq!(queue.segments.len(), 4);
        assert_eq!(queue.segments[0].start, 0);
        assert_eq!(queue.segments[0].end, 249);
        assert_eq!(queue.segments[3].end, 999);
    }

    #[test]
    fn test_work_stealing() {
        let mut queue = DynamicRangeQueue::new(2 * 1024 * 1024, 1); // 2 MB single chunk
        assert_eq!(queue.segments.len(), 1);
        let stolen = queue.try_steal_work();
        assert!(stolen.is_some());
        assert_eq!(queue.segments.len(), 2);
        let seg = stolen.unwrap();
        assert!(seg.start > 0);
    }

    #[test]
    fn partitioning_never_creates_empty_segments() {
        let queue = DynamicRangeQueue::new(3, 8);

        assert_eq!(queue.segments.len(), 3);
        assert_eq!(queue.segments[0].start, 0);
        assert_eq!(queue.segments[0].end, 0);
        assert_eq!(queue.segments[2].start, 2);
        assert_eq!(queue.segments[2].end, 2);
    }
}
