import albumentations.core.transforms_interface
import logging
import albumentations as A
from albumentations import GaussianBlur
from albumentations.augmentations import RandomBrightnessContrast


from donkeycar.config import Config


logger = logging.getLogger(__name__)

# Default probability used by ImageAugmentation at training time.
# Preview tools may override with prob=1.0; export should surface this value.
TRAINING_AUG_PROB = 0.5

# Declarative metadata for available training augmentations.
# Params map to config attributes; transform math lives in ImageAugmentation.create.
AUGMENTATION_REGISTRY = {
    'BRIGHTNESS': {
        'description': 'Random brightness and contrast adjustment',
        'params': {
            'AUG_BRIGHTNESS_RANGE': {
                'type': 'float',
                'default': 0.2,
                'min': 0.0,
                'max': 1.0,
                'step': 0.01,
                'description': 'Brightness/contrast limit (interpreted as [-v, v])',
            },
        },
    },
    'BLUR': {
        'description': 'Gaussian blur',
        'params': {
            'AUG_BLUR_RANGE': {
                'type': 'float_or_tuple',
                'default': 3,
                'min': 0.0,
                'max': 10.0,
                'step': 0.1,
                'description': 'GaussianBlur sigma_limit (float or (min, max) tuple)',
            },
        },
    },
}


class ImageAugmentation:
    def __init__(self, cfg, key, prob=TRAINING_AUG_PROB):
        aug_list = getattr(cfg, key, [])
        augmentations = [ImageAugmentation.create(a, cfg, prob)
                         for a in aug_list]
        self.augmentations = A.Compose(augmentations)

    @classmethod
    def create(cls, aug_type: str, config: Config, prob) -> \
            albumentations.core.transforms_interface.BasicTransform:
        """ Augmentation factory. Cropping and trapezoidal mask are
            transformations which should be applied in training, validation
            and inference. Multiply, Blur and similar are augmentations
            which should be used only in training. """

        if aug_type not in AUGMENTATION_REGISTRY:
            known = ', '.join(sorted(AUGMENTATION_REGISTRY.keys()))
            raise ValueError(
                f"Unknown augmentation type '{aug_type}'. "
                f"Known types: {known}"
            )

        if aug_type == 'BRIGHTNESS':
            default = AUGMENTATION_REGISTRY['BRIGHTNESS']['params'][
                'AUG_BRIGHTNESS_RANGE']['default']
            b_limit = getattr(config, 'AUG_BRIGHTNESS_RANGE', default)
            logger.info(f'Creating augmentation {aug_type} {b_limit}')
            return RandomBrightnessContrast(brightness_limit=b_limit,
                                            contrast_limit=b_limit,
                                            p=prob)

        elif aug_type == 'BLUR':
            default = AUGMENTATION_REGISTRY['BLUR']['params'][
                'AUG_BLUR_RANGE']['default']
            b_range = getattr(config, 'AUG_BLUR_RANGE', default)
            logger.info(f'Creating augmentation {aug_type} {b_range}')
            return GaussianBlur(sigma_limit=b_range, blur_limit=(13, 13),
                                p=prob)

        # Defensive: registry entry exists but no builder wired.
        raise ValueError(
            f"Augmentation '{aug_type}' is registered but has no factory "
            f"implementation"
        )

    # Parts interface
    def run(self, img_arr):
        if len(self.augmentations) == 0:
            return img_arr
        aug_img_arr = self.augmentations(image=img_arr)["image"]
        return aug_img_arr
