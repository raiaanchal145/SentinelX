import { Search } from "lucide-react"

type FilterOption = {
  label: string
  value: string
}

type Filter = {
  label: string
  value: string
  options: FilterOption[]
  onChange: (value: string) => void
}

type FilterBarProps = {
  searchPlaceholder?: string
  searchValue: string
  onSearchChange: (value: string) => void
  filters?: Filter[]
  onClear?: () => void
}

function FilterBar({
  searchPlaceholder = "Search...",
  searchValue,
  onSearchChange,
  filters = [],
  onClear,
}: FilterBarProps) {
  return (
    <div className="filter-bar">

      <div className="filter-search">
        <Search size={17} />

        <input
          value={searchValue}
          onChange={(e) =>
            onSearchChange(e.target.value)
          }
          placeholder={searchPlaceholder}
        />
      </div>

      {filters.map((filter) => (
        <select
          key={filter.label}
          value={filter.value}
          onChange={(e) =>
            filter.onChange(e.target.value)
          }
          className="filter-select"
        >
          {filter.options.map((option) => (
            <option
              key={option.value}
              value={option.value}
            >
              {option.label}
            </option>
          ))}
        </select>
      ))}

      {onClear && (
        <button
          type="button"
          onClick={onClear}
          className="clear-filter-button"
        >
          Clear filters
        </button>
      )}

    </div>
  )
}

export default FilterBar