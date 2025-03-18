# Nonprofit-Fundraise Linking Implementation Guide

## Backend Endpoints

1. **Search for nonprofits**:
   ```
   GET /api/organizations/non-profit/search/?searchTerm=example
   ```

2. **Create/retrieve a nonprofit**:
   ```
   POST /api/organizations/non-profit/create/
   {
     "name": "Example Nonprofit",
     "endaoment_org_id": "unique-id-from-endaoment",
     "ein": "123456789" (optional),
     "base_wallet_address": "0x..." (optional)
   }
   ```

3. **Link a nonprofit to a fundraise**:
   ```
   POST /api/organizations/non-profit/link-to-fundraise/
   {
     "nonprofit_id": 123,
     "fundraise_id": 456,
     "note": "Optional note about this link"
   }
   ```

## Implementation Flow

1. **Initial Publication**:
   - After creating a preregistration, retrieve/create the nonprofit using `create_nonprofit`
   - Link the nonprofit to the fundraise using `link_to_fundraise`
   - Store the note with department/lab information

2. **Republishing/Versioning**:
   - When updating a preregistration, a new Paper record is created with incremented version
   - After republishing, retrieve the same nonprofit using `create_nonprofit`
   - Create a new link to the new fundraise using `link_to_fundraise`
   - Reuse or update the note as needed

3. **Multiple Researchers**:
   - Different researchers can link the same nonprofit to different fundraises
   - Each link can have a unique note specifying department/lab

## Frontend Integration

### Example Hook Implementation

```typescript
import { useState } from 'react';
import { ApiClient } from '@/services/client';
import { ApiError } from '@/services/types';
import { ID } from '@/types/root';

interface NonprofitOrg {
  id: ID;
  name: string;
  ein: string;
  endaoment_org_id: string;
  base_wallet_address: string;
}

interface NonprofitFundraiseLink {
  id: ID;
  nonprofit: NonprofitOrg;
  fundraise: {
    id: ID;
    [key: string]: any;
  };
  note: string;
}

interface NonprofitLinkState {
  data: NonprofitFundraiseLink | null;
  isLoading: boolean;
  error: string | null;
}

type LinkNonprofitToFundraiseFn = (
  nonprofitData: {
    name: string;
    endaoment_org_id: string;
    ein?: string;
    base_wallet_address?: string;
  },
  fundraiseId: ID,
  note?: string
) => Promise<NonprofitFundraiseLink>;

type UseNonprofitLinkReturn = [NonprofitLinkState, LinkNonprofitToFundraiseFn];

/**
 * Hook for linking nonprofits to fundraises.
 * 
 * This hook provides a function to:
 * 1. Create or retrieve a nonprofit organization
 * 2. Link it to a fundraise
 * 
 * @returns [state, linkNonprofitToFundraise]
 */
export const useNonprofitLink = (): UseNonprofitLinkReturn => {
  const [data, setData] = useState<NonprofitFundraiseLink | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const linkNonprofitToFundraise: LinkNonprofitToFundraiseFn = async (
    nonprofitData,
    fundraiseId,
    note = ''
  ) => {
    setIsLoading(true);
    setError(null);

    try {
      // Step 1: Create or retrieve the nonprofit organization
      const nonprofitResponse = await ApiClient.post<NonprofitOrg>(
        '/api/organizations/non-profit/create/',
        nonprofitData
      );

      // Step 2: Link the nonprofit to the fundraise
      const linkPayload = {
        nonprofit_id: nonprofitResponse.id,
        fundraise_id: fundraiseId,
        note,
      };

      const linkResponse = await ApiClient.post<NonprofitFundraiseLink>(
        '/api/organizations/non-profit/link-to-fundraise/',
        linkPayload
      );

      setData(linkResponse);
      return linkResponse;
    } catch (err) {
      const { data = {} } = err instanceof ApiError ? JSON.parse(err.message) : {};
      const errorMsg = data?.error || 'An error occurred while linking the nonprofit to the fundraise';
      setError(errorMsg);
      throw err;
    } finally {
      setIsLoading(false);
    }
  };

  return [{ data, isLoading, error }, linkNonprofitToFundraise];
};
```

### Usage in PublishingForm Component

```tsx
import { useNonprofitLink } from '@/hooks/useNonprofitLink';

function PublishingForm() {
  const [{ isLoading: isLoadingNonprofitLink }, linkNonprofitToFundraise] = useNonprofitLink();
  
  const handlePublish = async () => {
    // First create the post/preregistration
    const response = await upsertPost({...});
    
    // If there's a selected nonprofit, link it to the fundraise
    if (selectedNonprofit && response.fundraise?.id) {
      try {
        await linkNonprofitToFundraise(
          {
            name: selectedNonprofit.name,
            endaoment_org_id: selectedNonprofit.endaoment_org_id,
            ein: selectedNonprofit.ein
          },
          response.fundraise.id,
          `Linked from preregistration ${response.id}`
        );
      } catch (error) {
        console.error('Error linking nonprofit:', error);
      }
    }
  };
  
  return (
    // Component JSX
  );
}
```

## Key Implementation Notes

1. The system supports multiple links between the same nonprofit and different fundraises
2. When republishing, create a new link to the new fundraise using the same nonprofit
3. Each department/lab can specify its own note in the link
4. The nonprofit record is reused across different fundraises and researchers
5. For versioned papers, each version gets its own fundraise and nonprofit link