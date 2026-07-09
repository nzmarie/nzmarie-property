#!/usr/bin/env python3
"""Test address formatting logic"""

def format_address(address_parts):
    """
    Smart address formatting with unit number detection.
    
    Examples:
        ['1', '10', 'barker', 'rise'] -> '1/10 Barker Rise'
        ['2', '23', 'cairnbrae', 'court'] -> '2/23 Cairnbrae Court'
        ['65', 'andersons', 'road'] -> '65 Andersons Road'
        ['1a', 'barker', 'rise'] -> '1A Barker Rise'
    """
    if not address_parts:
        return ""
    
    # Check if first two parts are numbers (unit/street number pattern)
    if len(address_parts) >= 2:
        first = address_parts[0]
        second = address_parts[1]
        
        # Pattern: "1 10" -> "1/10" (both are pure digits)
        if first.isdigit() and second.isdigit():
            # Unit number format
            unit_part = f"{first}/{second}"
            rest_parts = address_parts[2:]
            formatted_rest = ' '.join(rest_parts).title()
            return f"{unit_part} {formatted_rest}".strip()
    
    # Default: title case with spaces
    return ' '.join(address_parts).title()


# Test cases
test_cases = [
    (['1', '10', 'barker', 'rise'], '1/10 Barker Rise'),
    (['2', '23', 'cairnbrae', 'court'], '2/23 Cairnbrae Court'),
    (['1', '2', 'barker', 'rise'], '1/2 Barker Rise'),
    (['2', '2', 'barker', 'rise'], '2/2 Barker Rise'),
    (['65', 'andersons', 'road'], '65 Andersons Road'),
    (['1a', 'barker', 'rise'], '1A Barker Rise'),
    (['5', 'barker', 'rise'], '5 Barker Rise'),
    (['1', '16', 'barker', 'rise'], '1/16 Barker Rise'),
]

print("🧪 Testing Address Formatting Logic")
print("=" * 60)

all_passed = True
for parts, expected in test_cases:
    result = format_address(parts)
    passed = result == expected
    status = "✅" if passed else "❌"
    
    print(f"{status} {parts}")
    print(f"   Expected: {expected}")
    print(f"   Got:      {result}")
    
    if not passed:
        all_passed = False
    print()

print("=" * 60)
if all_passed:
    print("✅ All tests passed!")
else:
    print("❌ Some tests failed")
