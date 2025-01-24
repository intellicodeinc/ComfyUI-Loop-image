import torch
import torch.nn.functional as F
import cv2
import numpy as np


class MaskSplit:
    def __init__(self):
        pass
    
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE",),
                "mask": ("MASK",),

            },
        }
    
    RETURN_TYPES = ("IMAGE","MASK")
    RETURN_NAMES = ("segmented_images","segmented_masks")
    FUNCTION = "segment_mask"
    
    CATEGORY = "CyberEveLoop🐰"

    def find_top_left_point(self, mask_np):
        """找到mask中最左上角的点"""
        # 找到所有非零点
        y_coords, x_coords = np.nonzero(mask_np)
        if len(x_coords) == 0:
            return float('inf'), float('inf')
        
        # 找到最小x值
        min_x = np.min(x_coords)
        # 在最小x值的点中找到最小y值
        min_y = np.min(y_coords[x_coords == min_x])
        
        return min_x, min_y

    def segment_mask(self, mask, image):
        """使用OpenCV快速分割蒙版并处理图像"""
        # 保存原始设备信息
        device = mask.device if isinstance(mask, torch.Tensor) else torch.device('cpu')
        
        # 确保mask是正确的形状并转换为numpy数组
        if isinstance(mask, torch.Tensor):
            if len(mask.shape) == 2:
                mask = mask.unsqueeze(0)
            mask_np = (mask[0] * 255).cpu().numpy().astype(np.uint8)
        else:
            mask_np = (mask * 255).astype(np.uint8)
        
        # 使用OpenCV找到轮廓
        contours, hierarchy = cv2.findContours(
            mask_np, 
            cv2.RETR_TREE,
            cv2.CHAIN_APPROX_SIMPLE
        )
        
        mask_info = []  # 用于排序的信息列表
        
        if hierarchy is not None and len(contours) > 0:
            hierarchy = hierarchy[0]
            contour_masks = {}
            
            # 创建每个轮廓的mask
            for i, contour in enumerate(contours):
                mask = np.zeros_like(mask_np)
                cv2.drawContours(mask, [contour], -1, 255, -1)
                contour_masks[i] = mask

            # 处理每个轮廓
            processed_indices = set()
            
            for i, (contour, h) in enumerate(zip(contours, hierarchy)):
                if i in processed_indices:
                    continue
                    
                current_mask = contour_masks[i].copy()
                child_idx = h[2]
                
                if child_idx != -1:
                    while child_idx != -1:
                        current_mask = cv2.subtract(current_mask, contour_masks[child_idx])
                        processed_indices.add(child_idx)
                        child_idx = hierarchy[child_idx][0]
                
                # 找到最左上角的点
                min_x, min_y = self.find_top_left_point(current_mask)
                
                # 转换为tensor
                mask_tensor = torch.from_numpy(current_mask).float() / 255.0
                mask_tensor = mask_tensor.unsqueeze(0)
                mask_tensor = mask_tensor.to(device)
                
                # 保存mask和排序信息
                mask_info.append((mask_tensor, min_x, min_y))
                processed_indices.add(i)
        
        # 如果没有找到任何轮廓，使用原始mask
        if not mask_info:
            if isinstance(mask, torch.Tensor):
                mask_info.append((mask, 0, 0))
            else:
                mask_tensor = torch.from_numpy(mask).float()
                if len(mask_tensor.shape) == 2:
                    mask_tensor = mask_tensor.unsqueeze(0)
                mask_tensor = mask_tensor.to(device)
                mask_info.append((mask_tensor, 0, 0))
        
        # 根据最左上角点排序
        mask_info.sort(key=lambda x: (x[1], x[2]))
        
        # 确保image是正确的形状
        if len(image.shape) == 3:
            image = image.unsqueeze(0)
        
        # 处理masks和images
        result_masks = None
        result_images = None
        
        for mask_tensor, _, _ in mask_info:
            # 处理masks
            if result_masks is None:
                result_masks = mask_tensor
            else:
                result_masks = torch.cat([result_masks, mask_tensor], dim=0)
            
            # 处理images
            if result_images is None:
                result_images = image.clone()
            else:
                result_images = torch.cat([result_images, image.clone()], dim=0)
        
        return (result_images, result_masks)



class MaskMerge:
    def __init__(self):
        pass
    
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "original_image": ("IMAGE",),
            },
            "optional": {
                "processed_images": ("IMAGE", {"forceInput": True}),
                "masks": ("MASK", {"forceInput": True}),
            }
        }
    
    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("merged_image",)
    FUNCTION = "merge_masked_images"
    CATEGORY = "CyberEveLoop🐰"

    def standardize_input(self, image, processed_images=None, masks=None):
        """
        标准化输入格式
        - image: [H,W,C] -> [1,H,W,C]
        - processed_images: [...] -> [B,H,W,C]
        - masks: [...] -> [B,H,W]
        """
        # 处理原始图像
        if len(image.shape) == 3:
            image = image.unsqueeze(0)
        assert len(image.shape) == 4, f"Original image must be 4D [B,H,W,C], got shape {image.shape}"

        # 处理processed_images
        if processed_images is not None:
            if isinstance(processed_images, list):
                processed_images = torch.cat(processed_images, dim=0)
            if len(processed_images.shape) == 3:
                processed_images = processed_images.unsqueeze(0)
            assert len(processed_images.shape) == 4, \
                f"Processed images must be 4D [B,H,W,C], got shape {processed_images.shape}"

        # 处理masks
        if masks is not None:
            if isinstance(masks, list):
                masks = torch.cat(masks, dim=0)
            if len(masks.shape) == 2:
                masks = masks.unsqueeze(0)
            assert len(masks.shape) == 3, f"Masks must be 3D [B,H,W], got shape {masks.shape}"

        return image, processed_images, masks

    def resize_tensor(self, x, size, mode='bilinear'):
        """调整tensor尺寸的辅助函数"""
        # 确保输入是4D tensor [B,C,H,W]
        orig_dim = x.dim()
        if orig_dim == 3:
            x = x.unsqueeze(0)
        
        # 如果是图像 [B,H,W,C]，需要转换为 [B,C,H,W]
        if x.shape[-1] in [1, 3, 4]:
            x = x.permute(0, 3, 1, 2)
        
        # 执行调整
        x = F.interpolate(x, size=size, mode=mode, align_corners=False if mode in ['bilinear', 'bicubic'] else None)
        
        # 转换回原始格式
        if x.shape[1] in [1, 3, 4]:
            x = x.permute(0, 2, 3, 1)
        
        # 如果原始输入是3D，去掉batch维度
        if orig_dim == 3:
            x = x.squeeze(0)
            
        return x

    def merge_masked_images(self, original_image, processed_images=None, masks=None):
        """合并处理后的图像"""
        # 确保输入有效
        if processed_images is None or masks is None:
            return (original_image,)
        
        # 标准化输入
        original_image, processed_images, masks = self.standardize_input(
            original_image, processed_images, masks
        )
        
        # 创建结果图像的副本
        result = original_image.clone()
        
        # 获取目标尺寸
        target_height = original_image.shape[1]
        target_width = original_image.shape[2]
        
        # 调整处理图像的尺寸（如果需要）
        if processed_images.shape[1:3] != (target_height, target_width):
            processed_images = self.resize_tensor(
                processed_images,
                (target_height, target_width),
                mode='bilinear'
            )
        
        # 调整蒙版尺寸（如果需要）
        if masks.shape[1:3] != (target_height, target_width):
            masks = self.resize_tensor(
                masks,
                (target_height, target_width),
                mode='bilinear'
            )
        
        # 扩展蒙版维度以匹配图像通道
        masks = masks.unsqueeze(-1).expand(-1, -1, -1, 3)
        
        # 批量处理所有图片
        for i in range(processed_images.shape[0]):
            current_image = processed_images[i:i+1]
            current_mask = masks[i:i+1]
            result = current_mask * current_image + (1 - current_mask) * result
        
        assert len(result.shape) == 4, "Output must be 4D [B,H,W,C]"
        return (result,)
    

Mask_CLASS_MAPPINGS = {
    "CyberEve_MaskSegmentation": MaskSplit,
    "CyberEve_MaskMerge": MaskMerge,
}

Mask_DISPLAY_NAME_MAPPINGS = {
    "CyberEve_MaskSegmentation": "Mask Segmentation🐰",
    "CyberEve_MaskMerge": "Mask Merge🐰",
}

