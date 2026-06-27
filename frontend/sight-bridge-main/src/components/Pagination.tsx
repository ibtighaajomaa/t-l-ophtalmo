import { ChevronLeft, ChevronRight } from "lucide-react";

interface PaginationProps {
  currentPage: number;
  totalPages: number;
  onPageChange: (page: number) => void;
}

export function Pagination({ currentPage, totalPages, onPageChange }: PaginationProps) {
  const totalPagesCount = Math.max(totalPages, 1);
  const getVisiblePages = (current: number, total: number) => {
    if (total <= 7) {
      return Array.from({ length: total }, (_, i) => i + 1);
    }

    if (current <= 4) {
      return [1, 2, 3, 4, 5, '...', total];
    }

    if (current >= total - 3) {
      return [1, '...', total - 4, total - 3, total - 2, total - 1, total];
    }

    return [1, '...', current - 1, current, current + 1, '...', total];
  };

  const visiblePages = getVisiblePages(currentPage, totalPagesCount);

  return (
    <div className="flex items-center justify-between border-t border-slate-100 bg-white px-4 py-3 sm:px-6 mt-4">
      {/* Mobile view */}
      <div className="flex flex-1 justify-between sm:hidden">
        <button
          disabled={currentPage === 1}
          onClick={() => onPageChange(currentPage - 1)}
          className="relative inline-flex items-center rounded-md border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50 disabled:cursor-not-allowed transition duration-150"
        >
          Précédent
        </button>
        <button
          disabled={currentPage === totalPagesCount}
          onClick={() => onPageChange(currentPage + 1)}
          className="relative ml-3 inline-flex items-center rounded-md border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50 disabled:cursor-not-allowed transition duration-150"
        >
          Suivant
        </button>
      </div>

      {/* Desktop view */}
      <div className="hidden sm:flex sm:flex-1 sm:items-center sm:justify-between">
        <div>
          <p className="text-sm text-slate-500">
            Page <span className="font-semibold text-slate-900">{currentPage}</span> sur{" "}
            <span className="font-semibold text-slate-900">{totalPagesCount}</span>
          </p>
        </div>
        <div>
          <nav className="isolate inline-flex -space-x-px rounded-lg shadow-sm bg-slate-50 p-1" aria-label="Pagination">
            <button
              disabled={currentPage === 1}
              onClick={() => onPageChange(currentPage - 1)}
              className="relative inline-flex items-center rounded-md px-2 py-1.5 text-slate-500 hover:bg-white hover:text-slate-700 disabled:opacity-30 disabled:cursor-not-allowed transition-all duration-150 mr-1"
            >
              <span className="sr-only">Précédent</span>
              <ChevronLeft className="h-4 w-4" />
            </button>
            {visiblePages.map((p, idx) => (
              p === '...' ? (
                <span
                  key={`ellipsis-${idx}`}
                  className="relative inline-flex items-center px-3 py-1.5 text-sm font-semibold text-slate-600 mx-0.5"
                >
                  ...
                </span>
              ) : (
                <button
                  key={p}
                  onClick={() => onPageChange(p as number)}
                  className={`relative inline-flex items-center rounded-md px-3 py-1.5 text-sm font-semibold transition-all duration-150 mx-0.5 ${
                    currentPage === p
                      ? "bg-blue-600 text-white shadow-sm"
                      : "text-slate-600 hover:bg-white hover:text-slate-800"
                  }`}
                >
                  {p}
                </button>
              )
            ))}
            <button
              disabled={currentPage === totalPagesCount}
              onClick={() => onPageChange(currentPage + 1)}
              className="relative inline-flex items-center rounded-md px-2 py-1.5 text-slate-500 hover:bg-white hover:text-slate-700 disabled:opacity-30 disabled:cursor-not-allowed transition-all duration-150 ml-1"
            >
              <span className="sr-only">Suivant</span>
              <ChevronRight className="h-4 w-4" />
            </button>
          </nav>
        </div>
      </div>
    </div>
  );
}
