'use client'

import { useEffect, useId, useRef, useState, KeyboardEvent as ReactKeyboardEvent } from 'react'
import { Check, ChevronDown, Search } from 'lucide-react'

export type SelectOption = {
  value: string
  label: string
  group?: string
}

type CustomSelectProps = {
  value: string
  onChange: (value: string) => void
  options: (string | SelectOption)[]
  label?: string
  ariaLabel?: string
  placeholder?: string
  disabled?: boolean
  searchable?: boolean
  className?: string
  buttonClassName?: string
}

export function CustomSelect({
  value,
  onChange,
  options,
  label,
  ariaLabel,
  placeholder = 'Select option...',
  disabled = false,
  searchable = false,
  className = '',
  buttonClassName = '',
}: CustomSelectProps) {
  const [isOpen, setIsOpen] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const [highlightedIndex, setHighlightedIndex] = useState(-1)
  const [dropdownPos, setDropdownPos] = useState<{ top: number; left: number; width: number; placement: 'bottom' | 'top' }>({
    top: 0,
    left: 0,
    width: 160,
    placement: 'bottom',
  })

  const containerRef = useRef<HTMLDivElement>(null)
  const buttonRef = useRef<HTMLButtonElement>(null)
  const dropdownRef = useRef<HTMLDivElement>(null)
  const listboxRef = useRef<HTMLUListElement>(null)
  const searchInputRef = useRef<HTMLInputElement>(null)
  const selectId = useId()

  const normalizedOptions: SelectOption[] = options.map(opt =>
    typeof opt === 'string' ? { value: opt, label: opt } : opt
  )

  const selectedOption = normalizedOptions.find(opt => opt.value === value)
  const isSearchActive = searchable || normalizedOptions.length > 8
  const filteredOptions = isSearchActive && searchQuery
    ? normalizedOptions.filter(opt =>
        opt.label.toLowerCase().includes(searchQuery.toLowerCase()) ||
        opt.value.toLowerCase().includes(searchQuery.toLowerCase())
      )
    : normalizedOptions

  // Position calculation for dropdown (prevent clipping)
  const updatePosition = () => {
    if (!buttonRef.current) return
    const rect = buttonRef.current.getBoundingClientRect()
    const viewportHeight = window.innerHeight
    const viewportWidth = window.innerWidth
    const estimatedHeight = Math.min(260, (filteredOptions.length + (isSearchActive ? 1 : 0)) * 40 + 20)

    const spaceBelow = viewportHeight - rect.bottom
    const spaceAbove = rect.top
    const placement = spaceBelow < estimatedHeight && spaceAbove > spaceBelow ? 'top' : 'bottom'

    let top = placement === 'bottom' ? rect.bottom + 4 : rect.top - estimatedHeight - 4
    let left = rect.left
    const minWidth = Math.max(rect.width, 160)
    const maxWidth = Math.min(320, viewportWidth - 16)

    if (left + minWidth > viewportWidth - 8) {
      left = Math.max(8, viewportWidth - minWidth - 8)
    }

    setDropdownPos({
      top: Math.max(8, top),
      left: Math.max(8, left),
      width: minWidth,
      placement,
    })
  }

  // Update position when opening, resizing, or scrolling
  useEffect(() => {
    if (isOpen) {
      updatePosition()
      window.addEventListener('resize', updatePosition)
      window.addEventListener('scroll', updatePosition, true)
    } else {
      setSearchQuery('')
    }
    return () => {
      window.removeEventListener('resize', updatePosition)
      window.removeEventListener('scroll', updatePosition, true)
    }
  }, [isOpen, filteredOptions.length])

  // Close when clicking outside
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      const target = event.target as Node
      if (
        containerRef.current &&
        !containerRef.current.contains(target) &&
        dropdownRef.current &&
        !dropdownRef.current.contains(target)
      ) {
        setIsOpen(false)
      }
    }
    if (isOpen) {
      document.addEventListener('mousedown', handleClickOutside)
    }
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [isOpen])

  // Focus search input or listbox when menu opens
  useEffect(() => {
    if (isOpen) {
      const initialIndex = filteredOptions.findIndex(opt => opt.value === value)
      setHighlightedIndex(initialIndex >= 0 ? initialIndex : 0)
      if (isSearchActive && searchInputRef.current) {
        setTimeout(() => searchInputRef.current?.focus(), 20)
      }
    }
  }, [isOpen])

  // Scroll highlighted item into view
  useEffect(() => {
    if (isOpen && highlightedIndex >= 0 && listboxRef.current) {
      const item = listboxRef.current.children[highlightedIndex] as HTMLElement
      if (item) {
        item.scrollIntoView({ block: 'nearest' })
      }
    }
  }, [highlightedIndex, isOpen])

  function handleSelect(val: string) {
    onChange(val)
    setIsOpen(false)
    buttonRef.current?.focus()
  }

  function handleButtonKeyDown(event: ReactKeyboardEvent) {
    if (disabled) return

    switch (event.key) {
      case 'Enter':
      case ' ':
      case 'ArrowDown':
      case 'ArrowUp':
        event.preventDefault()
        if (!isOpen) {
          setIsOpen(true)
        } else if (event.key === 'ArrowDown') {
          setHighlightedIndex(prev => (prev + 1) % Math.max(1, filteredOptions.length))
        } else if (event.key === 'ArrowUp') {
          setHighlightedIndex(prev => (prev - 1 + filteredOptions.length) % Math.max(1, filteredOptions.length))
        } else if (highlightedIndex >= 0 && highlightedIndex < filteredOptions.length) {
          handleSelect(filteredOptions[highlightedIndex].value)
        }
        break
      case 'Escape':
        if (isOpen) {
          event.preventDefault()
          setIsOpen(false)
          buttonRef.current?.focus()
        }
        break
      case 'Tab':
        if (isOpen) {
          setIsOpen(false)
        }
        break
    }
  }

  function handleSearchKeyDown(event: ReactKeyboardEvent) {
    // Space typed inside search field must insert space and NOT select option or close menu
    if (event.key === ' ') {
      event.stopPropagation()
      return
    }

    if (event.key === 'ArrowDown') {
      event.preventDefault()
      setHighlightedIndex(prev => (prev + 1) % Math.max(1, filteredOptions.length))
    } else if (event.key === 'ArrowUp') {
      event.preventDefault()
      setHighlightedIndex(prev => (prev - 1 + filteredOptions.length) % Math.max(1, filteredOptions.length))
    } else if (event.key === 'Enter') {
      event.preventDefault()
      if (highlightedIndex >= 0 && highlightedIndex < filteredOptions.length) {
        handleSelect(filteredOptions[highlightedIndex].value)
      }
    } else if (event.key === 'Escape') {
      event.preventDefault()
      setIsOpen(false)
      buttonRef.current?.focus()
    } else if (event.key === 'Tab') {
      setIsOpen(false)
    }
  }

  const activeDescendantId = isOpen && highlightedIndex >= 0 && highlightedIndex < filteredOptions.length
    ? `${selectId}-opt-${highlightedIndex}`
    : undefined

  return (
    <div
      ref={containerRef}
      className={`custom-select-container ${className}`}
      style={{ position: 'relative', display: 'inline-flex', flexDirection: 'column', width: '100%' }}
    >
      {label && (
        <label
          htmlFor={`${selectId}-button`}
          className="custom-select-label"
          style={{
            fontSize: '10px',
            fontWeight: 650,
            textTransform: 'uppercase',
            letterSpacing: '0.05em',
            color: 'var(--muted)',
            marginBottom: '4px',
            display: 'block',
          }}
        >
          {label}
        </label>
      )}

      <button
        id={`${selectId}-button`}
        ref={buttonRef}
        type="button"
        role="combobox"
        aria-haspopup="listbox"
        aria-expanded={isOpen}
        aria-controls={`${selectId}-listbox`}
        aria-activedescendant={activeDescendantId}
        aria-label={ariaLabel || label || 'Select'}
        disabled={disabled}
        onClick={() => setIsOpen(prev => !prev)}
        onKeyDown={handleButtonKeyDown}
        className={`custom-select-button ${buttonClassName}`}
        style={{
          minHeight: '40px',
          height: '40px',
          padding: '0 12px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: '8px',
          backgroundColor: 'var(--panel-2)',
          color: 'var(--text)',
          border: '1px solid var(--line)',
          borderRadius: '8px',
          fontSize: '12px',
          fontWeight: 500,
          cursor: disabled ? 'not-allowed' : 'pointer',
          opacity: disabled ? 0.6 : 1,
          width: '100%',
          textAlign: 'left',
          transition: 'border-color 150ms ease, box-shadow 150ms ease',
        }}
      >
        <span
          className="custom-select-value"
          style={{
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
            flex: 1,
          }}
        >
          {selectedOption ? selectedOption.label : placeholder}
        </span>
        <ChevronDown
          size={14}
          style={{
            flexShrink: 0,
            color: 'var(--muted)',
            transition: 'transform 180ms ease',
            transform: isOpen ? 'rotate(180deg)' : 'rotate(0deg)',
          }}
        />
      </button>

      {isOpen && (
        <div
          ref={dropdownRef}
          className="custom-select-dropdown"
          style={{
            position: 'fixed',
            top: `${dropdownPos.top}px`,
            left: `${dropdownPos.left}px`,
            width: `${dropdownPos.width}px`,
            maxHeight: '280px',
            zIndex: 99999,
            backgroundColor: 'var(--panel)',
            border: '1px solid var(--line)',
            borderRadius: '10px',
            boxShadow: '0 16px 36px rgba(0, 0, 0, 0.45)',
            overflow: 'hidden',
            animation: 'customSelectFadeIn 120ms ease-out',
          }}
        >
          {isSearchActive && (
            <div
              style={{
                padding: '8px',
                borderBottom: '1px solid var(--line)',
                display: 'flex',
                alignItems: 'center',
                gap: '6px',
                backgroundColor: 'var(--panel-2)',
              }}
            >
              <Search size={13} style={{ color: 'var(--muted)', flexShrink: 0 }} />
              <input
                ref={searchInputRef}
                type="text"
                value={searchQuery}
                onChange={e => setSearchQuery(e.target.value)}
                onKeyDown={handleSearchKeyDown}
                placeholder="Search options..."
                aria-label="Filter options"
                aria-controls={`${selectId}-listbox`}
                aria-activedescendant={activeDescendantId}
                style={{
                  width: '100%',
                  background: 'transparent',
                  border: 'none',
                  outline: 'none',
                  color: 'var(--text)',
                  fontSize: '12px',
                  padding: '2px 0',
                }}
              />
            </div>
          )}

          <ul
            id={`${selectId}-listbox`}
            ref={listboxRef}
            role="listbox"
            aria-label={ariaLabel || label || 'Options'}
            style={{
              maxHeight: '220px',
              overflowY: 'auto',
              margin: 0,
              padding: '4px',
              listStyle: 'none',
            }}
          >
            {filteredOptions.length === 0 ? (
              <li
                style={{
                  padding: '10px 12px',
                  fontSize: '12px',
                  color: 'var(--faint)',
                  textAlign: 'center',
                }}
              >
                No matching options
              </li>
            ) : (
              filteredOptions.map((opt, idx) => {
                const isSelected = opt.value === value
                const isHighlighted = idx === highlightedIndex
                const optionId = `${selectId}-opt-${idx}`

                return (
                  <li
                    key={opt.value}
                    id={optionId}
                    role="option"
                    aria-selected={isSelected}
                    onClick={() => handleSelect(opt.value)}
                    onMouseEnter={() => setHighlightedIndex(idx)}
                    style={{
                      minHeight: '40px',
                      padding: '8px 12px',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      gap: '8px',
                      borderRadius: '6px',
                      fontSize: '12px',
                      fontWeight: isSelected ? 600 : 400,
                      color: isSelected ? 'var(--text)' : 'var(--muted)',
                      backgroundColor: isHighlighted
                        ? 'var(--panel-3)'
                        : isSelected
                        ? 'var(--blue-soft)'
                        : 'transparent',
                      cursor: 'pointer',
                      transition: 'background-color 100ms ease, color 100ms ease',
                    }}
                  >
                    <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {opt.label}
                    </span>
                    {isSelected && (
                      <Check size={14} style={{ color: 'var(--blue)', flexShrink: 0 }} />
                    )}
                  </li>
                )
              })
            )}
          </ul>
        </div>
      )}
    </div>
  )
}
