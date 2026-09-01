export function SkeletonQuestion() {
  return (
    <div className="card" aria-busy="true" aria-label="Loading question">
      <div className="skeleton h-5 w-3/4" />
      <div className="skeleton mt-2 h-5 w-1/2" />
      <div className="mt-6 space-y-2">
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="skeleton h-12 w-full" />
        ))}
      </div>
    </div>
  );
}

export function SkeletonLines({ count = 3 }: { count?: number }) {
  return (
    <div className="space-y-2" aria-busy="true">
      {Array.from({ length: count }, (_, i) => (
        <div key={i} className="skeleton h-4" style={{ width: `${90 - i * 12}%` }} />
      ))}
    </div>
  );
}
